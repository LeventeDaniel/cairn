import { expect, test } from 'claude-code/testing'

const BAND = {
  plugin: 'cairn',
  component: 'AbovePrompt',
  props: {
    hasSurvey: false, isCollapsed: false, isWorking: false, bodyColumns: 100, maxRows: 4,
    scroll: { offset: 0, bodyRows: 3 }, view: {},
  },
} as const

const PCT_ONLY = {
  compact_soft_tokens: 0, compact_at_tokens: 0, compact_hard_tokens: 0,
  home_compact_soft_tokens: 0, home_compact_at_tokens: 0, home_compact_hard_tokens: 0,
}

type Seen = { compacts: number; toasts: string[]; release: () => void; releaseCache: () => void; stored: Record<string, unknown> }

/** An engine at `percent` context; long timers (the idle one) wait for `seen.release()`. */
function engine(on: any, percent: number, opt: { now?: number; ends?: unknown; cwd?: string; failCompact?: boolean; board?: unknown; cfg?: object } = {}): Seen {
  const seen: Seen = { compacts: 0, toasts: [], release: () => {}, releaseCache: () => {}, stored: {} }
  const gate = new Promise<void>(r => { seen.release = r })
  const cacheGate = new Promise<void>(r => { seen.releaseCache = r })
  if (opt.ends) seen.stored.lastEnd = opt.ends
  on('store.get', (_: any, e: any) => ({ value: seen.stored[e.key] }))
  on('store.set', (_: any, e: any) => { seen.stored[e.key] = e.value; return { value: undefined } })
  on('command.register', () => ({ value: { command: 'cairn' } }))
  on('ui.open', () => ({ value: { isPlaced: true } }))
  on('session.start', (_: any, e: any) => ({ cwd: e.cwd }))
  on('session.id', () => ({ value: 's1' }))
  on('session.cwd', () => ({ value: opt.cwd ?? 'C:/r/example-a' }))
  on('session.usage', () => ({ value: {
    startedAt: 0, context: { tokens: percent * 10000, window: 1000000, percent }, rateLimits: [] } }))
  // These tests are about the percentage steps (the test window is 1M tokens, so 50% is 500k): the token
  // steps are switched off unless a test passes its own config.
  const config = JSON.stringify(opt.cfg ?? PCT_ONLY)
  on('fs.read', (_: any, e: any) => ({ value: opt.board && String(e.path).endsWith('board.json') ? JSON.stringify(opt.board)
    : String(e.path).endsWith('config.json') ? config : '{}' }))
  on('fs.list', () => ({ value: [] }))
  on('fs.write', () => ({ value: undefined }))
  on('ui.toast', (_: any, e: any) => { seen.toasts.push(e.text); return { value: undefined } })
  on('ui.status', () => ({ value: undefined }))
  on('ui.log', () => ({ value: undefined }))
  on('clock.now', () => ({ value: opt.now ?? 1000 }))
  on('clock.after', async (_: any, e: any) => {
    if (e.ms >= 30 * 60000) await cacheGate   // the prompt-cache guard
    else if (e.ms > 10000) await gate         // the idle offer
    return { value: undefined }
  })
  on('tool.call', (_: any, e: any) =>
    e.tool === 'Bash' && e.command === 'npm test' && !(globalThis as any).__pass
      ? { isError: true, result: 'FAIL', text: 'FAIL a.test.ts' }
      : { result: {}, text: 'ok' })
  on('turn.start', (_: any, e: any) => ({ turnId: e.turnId }))
  on('turn.complete', (_: any, e: any) => ({ text: e.answer }))
  on('session.measure', (_: any, e: any) => ({ changed: e.changed }))
  on('command.run', (_: any, e: any) => {
    if (e.command === 'compact') {
      if (opt.failCompact) throw new Error('refused')
      seen.compacts++
    }
    return { text: 'ok' }
  })
  return seen
}

async function turn($: any, work: () => Promise<unknown>) {
  await $.turn.start({ turnId: 't', text: 'go' } as any)
  await work()
  await $.turn.complete({ turnId: 't', reason: 'answer', answer: 'done', durationMs: 1, isAborted: false } as any)
}

const settle = async () => { for (let i = 0; i < 300; i++) await Promise.resolve() }

test('a finished task at 50% is offered in the band; Compact now runs it', async ($, on) => {
  const seen = engine(on, 50)
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
  await turn($, () => $.tool.call({ tool: 'mcp__ccd_turn__wrap_up', recap: 'x' } as any))
  await settle()
  expect(seen.compacts).toBe(0)

  const ui = await $.ui.mount({ ...BAND, surface: 'desktop' } as any)
  expect((await ui.find({ type: 'Text', text: /good moment to compact/ }))?.text).toContain('task wrapped up')
  await ui.press({ key: 'now' })
  await settle()
  expect(seen.compacts).toBe(1)
  await ui.unmount()
})

test('a calm turn end at 50% with nothing finished just waits', async ($, on) => {
  const seen = engine(on, 50)
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
  await turn($, () => $.tool.call({ tool: 'Read', file_path: 'C:/a.ts' } as any))
  await settle()
  const ui = await $.ui.mount({ ...BAND, surface: 'terminal' } as any)
  expect(await ui.find({ type: 'Text', text: /good moment/ })).toBeUndefined()
  await ui.unmount()
  expect(seen.compacts).toBe(0)
})

test('a commit at 65% compacts right away', async ($, on) => {
  const seen = engine(on, 65)
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
  await turn($, () => $.tool.call({ tool: 'Bash', command: 'git commit -m "x"' } as any))
  await settle()
  expect(seen.compacts).toBe(1)
  expect(seen.toasts.some(t => t.includes('work committed'))).toBe(true)
})

test('an open failure at 65% waits; at the hard limit it compacts anyway', async ($, on) => {
  let seen = engine(on, 65)
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
  await turn($, () => $.tool.call({ tool: 'Bash', command: 'npm test' } as any))
  await settle()
  expect(seen.compacts).toBe(0)
  await $.session.measure({ context: { tokens: 750000, window: 1000000, percent: 75 }, rateLimits: [], changed: ['context'] } as any)
  await turn($, () => $.tool.call({ tool: 'Read', file_path: 'C:/a.ts' } as any))
  await settle()
  expect(seen.compacts).toBe(1)
  expect(seen.toasts.some(t => t.includes('before auto-compact'))).toBe(true)
})

test('an offer nobody answers runs once the person has been away', async ($, on) => {
  const seen = engine(on, 62)
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
  await turn($, () => $.tool.call({ tool: 'Read', file_path: 'C:/a.ts' } as any))
  await settle()
  expect(seen.compacts).toBe(0)
  seen.release()               // idle_minutes pass with no new turn
  await settle()
  expect(seen.compacts).toBe(1)
  expect(seen.toasts.some(t => t.includes('while you were away'))).toBe(true)
})

test('Not now hides the offer until context grows 10 more points', async ($, on) => {
  const seen = engine(on, 62)
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
  await turn($, () => $.tool.call({ tool: 'Read', file_path: 'C:/a.ts' } as any))
  await settle()
  const ui = await $.ui.mount({ ...BAND, surface: 'desktop' } as any)
  await ui.press({ key: 'later' })
  await settle()
  expect(await ui.find({ type: 'Text', text: /good moment/ })).toBeUndefined()
  await turn($, () => $.tool.call({ tool: 'Read', file_path: 'C:/b.ts' } as any))
  await settle()
  expect(await ui.find({ type: 'Text', text: /good moment/ })).toBeUndefined()
  await ui.unmount()
  seen.release()
  await settle()
  expect(seen.compacts).toBe(0)
})

test('a wrap-up that still asks something is not a finished task', async ($, on) => {
  engine(on, 50)
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
  await turn($, () => $.tool.call({ tool: 'mcp__ccd_turn__wrap_up', recap: 'x', ask: 'Push it?' } as any))
  await settle()
  const ui = await $.ui.mount({ ...BAND, surface: 'desktop' } as any)
  expect(await ui.find({ type: 'Text', text: /good moment/ })).toBeUndefined()
  await ui.unmount()
})

test('a failure left from an earlier turn does not block the offer once the task is wrapped up', async ($, on) => {
  const seen = engine(on, 50)
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
  await turn($, () => $.tool.call({ tool: 'Bash', command: 'npm test' } as any))
  await settle()
  await turn($, () => $.tool.call({ tool: 'mcp__ccd_turn__wrap_up', recap: 'x' } as any))
  await settle()
  const ui = await $.ui.mount({ ...BAND, surface: 'desktop' } as any)
  expect((await ui.find({ type: 'Text', text: /good moment to compact/ }))?.text).toContain('task wrapped up')
  await ui.unmount()
  expect(seen.compacts).toBe(0)
})

test('an idle context big enough to matter is compacted before the prompt cache expires', async ($, on) => {
  const seen = engine(on, 10)   // 100k tokens: below every % threshold
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
  await turn($, () => $.tool.call({ tool: 'Read', file_path: 'C:/a.ts' } as any))
  await settle()
  seen.release()
  await settle()
  expect(seen.compacts).toBe(0)
  seen.releaseCache()           // 55 minutes with no new turn
  await settle(); await settle() // the guard reads the board first: a few more hops
  expect(seen.compacts).toBe(1)
  expect(seen.toasts.some(t => t.includes('before the prompt cache expired'))).toBe(true)
})

test('a small context is left alone when the cache expires', async ($, on) => {
  const seen = engine(on, 3)    // 30k tokens: a cold re-read is cheap
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
  await turn($, () => $.tool.call({ tool: 'Read', file_path: 'C:/a.ts' } as any))
  await settle()
  seen.releaseCache()
  await settle()
  expect(seen.compacts).toBe(0)
})

test('Not now also holds off the cache guard', async ($, on) => {
  const seen = engine(on, 62)
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
  await turn($, () => $.tool.call({ tool: 'Read', file_path: 'C:/a.ts' } as any))
  await settle()
  const ui = await $.ui.mount({ ...BAND, surface: 'desktop' } as any)
  await ui.press({ key: 'later' })
  await ui.unmount()
  seen.release(); seen.releaseCache()
  await settle()
  expect(seen.compacts).toBe(0)
})

test('each turn end is noted, so a later start can tell the cache went cold', async ($, on) => {
  const seen = engine(on, 20)
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
  await turn($, () => $.tool.call({ tool: 'Read', file_path: 'C:/a.ts' } as any))
  await settle()
  expect((seen.stored.lastEnd as any).s1).toEqual({ at: 1000, tokens: 200000 })
})

test('a big session started after the cache expired is offered a compaction, never given one', async ($, on) => {
  // An app restart starts every open session at once; compacting them all on a cold cache is a full-price
  // read each (this took a quarter of a 5-hour limit in seconds). The band waits for the person instead.
  const seen = engine(on, 20, { now: 3 * 3600000, ends: { s1: { at: 0, tokens: 200000 } } })
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
  for (let i = 0; i < 5; i++) await settle()
  seen.release(); seen.releaseCache()
  for (let i = 0; i < 5; i++) await settle()
  expect(seen.compacts).toBe(0)
  expect(seen.toasts.some(t => t.includes('compacting'))).toBe(false)
  const ui = await $.ui.mount({ ...BAND, surface: 'desktop' } as any)
  expect((await ui.find({ type: 'Text', text: /compact before you continue/ }))?.text).toContain('away 3 h')
  await ui.press({ key: 'now' })   // the person is back and says yes
  await settle()
  expect(seen.compacts).toBe(1)
})

test('after a cold start the banner stays up until someone answers it', async ($, on) => {
  const seen = engine(on, 20, { now: 3 * 3600000, ends: { s1: { at: 0, tokens: 200000 } }, failCompact: true })
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
  for (let i = 0; i < 20; i++) await settle()   // all retries used up
  expect(seen.compacts).toBe(0)
  const ui = await $.ui.mount({ ...BAND, surface: 'desktop' } as any)
  expect((await ui.find({ type: 'Text', text: /compact before you continue/ }))?.text).toContain('away 3 h')
  await ui.unmount()
})

test('the fallback banner names the idle time and the tokens at stake', async ($, on) => {
  const seen = engine(on, 20, { now: 3 * 3600000, ends: { s1: { at: 0, tokens: 200000 } }, failCompact: true })
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
  for (let i = 0; i < 20; i++) await settle()   // all retries used up
  const ui = await $.ui.mount({ ...BAND, surface: 'desktop' } as any)
  const t = (await ui.find({ type: 'Text', text: /compact before you continue/ }))?.text
  expect(t).toContain('away 3 h')
  expect(t).toContain('200k tokens')
  expect(t?.includes('runs by itself')).toBe(false)
  await ui.unmount()
  expect(seen.compacts).toBe(0)
})

test('a session resumed while the cache is still warm gets no offer', async ($, on) => {
  engine(on, 20, { now: 30 * 60000, ends: { s1: { at: 0, tokens: 200000 } } })
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
  await settle()
  const ui = await $.ui.mount({ ...BAND, surface: 'desktop' } as any)
  expect(await ui.find({ type: 'Text', text: /compact/ })).toBeUndefined()
  await ui.unmount()
})

test('in Cairn Home a wrapped-up turn at 20% is already offered (home thresholds)', async ($, on) => {
  engine(on, 20, { cwd: String.raw`C:\Users\me\.claude\cairn\home` })
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
  await turn($, () => $.tool.call({ tool: 'mcp__ccd_turn__wrap_up', recap: 'x' } as any))
  await settle()
  const ui = await $.ui.mount({ ...BAND, surface: 'desktop' } as any)
  expect((await ui.find({ type: 'Text', text: /good moment to compact/ }))).toBeTruthy()
  await ui.unmount()
})

test('in Cairn Home 50% is past the hard limit: compacts at the turn end', async ($, on) => {
  const seen = engine(on, 55, { cwd: 'C:/Users/me/.claude/cairn/home' })
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
  await turn($, () => $.tool.call({ tool: 'Read', file_path: 'C:/a.ts' } as any))
  await settle()
  expect(seen.compacts).toBe(1)
})

test('in a repo, a wrapped-up turn at 20% stays below compact_soft', async ($, on) => {
  const seen = engine(on, 20)
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
  await turn($, () => $.tool.call({ tool: 'mcp__ccd_turn__wrap_up', recap: 'x' } as any))
  await settle()
  const ui = await $.ui.mount({ ...BAND, surface: 'desktop' } as any)
  expect((await ui.find({ type: 'Text', text: /good moment to compact/ }))).toBeFalsy()
  expect(seen.compacts).toBe(0)
  await ui.unmount()
})

// A worker whose board task is finished gets no more messages: compacting it while idle only spends plan usage.
const DONE_BOARD = { tasks: [{ id: 't1', cliSession: 's1', status: 'done' }] }

test('a finished worker is not compacted while it sits idle, the offer stays', async ($, on) => {
  const seen = engine(on, 62, { board: DONE_BOARD })
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
  await turn($, () => $.tool.call({ tool: 'Read', file_path: 'C:/a.ts' } as any))
  await settle()
  seen.release(); seen.releaseCache()   // the idle minutes and the cache guard both pass
  for (let i = 0; i < 5; i++) await settle()
  expect(seen.compacts).toBe(0)
  const ui = await $.ui.mount({ ...BAND, surface: 'desktop' } as any)
  expect(await ui.find({ type: 'Text', text: /good moment to compact/ })).toBeDefined()
  await ui.unmount()
})

test('a finished worker reopened after the cache expired is offered a compaction, not given one', async ($, on) => {
  const seen = engine(on, 20, { now: 3 * 3600000, ends: { s1: { at: 0, tokens: 200000 } }, board: DONE_BOARD })
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
  for (let i = 0; i < 5; i++) await settle()
  expect(seen.compacts).toBe(0)
  const ui = await $.ui.mount({ ...BAND, surface: 'desktop' } as any)
  expect(await ui.find({ type: 'Text', text: /compact before you continue/ })).toBeDefined()
  await ui.unmount()
})

test('a worker whose task is still open is compacted as before', async ($, on) => {
  const seen = engine(on, 62, { board: { tasks: [{ id: 't1', cliSession: 's1', status: 'waiting' }, { id: 't0', cliSession: 'other', status: 'done' }] } })
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
  await turn($, () => $.tool.call({ tool: 'Read', file_path: 'C:/a.ts' } as any))
  await settle()
  seen.release()
  await settle()
  expect(seen.compacts).toBe(1)
})

// ---- token steps (the defaults): a 1M-token window must not wait for 40% = 400k tokens
test('on a 1M window a finished task at 150k tokens is offered, and runs if nobody answers', async ($, on) => {
  const seen = engine(on, 15, { cfg: {} })   // 150k of 1M: 15%, far below compact_soft 40%
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
  await turn($, () => $.tool.call({ tool: 'mcp__ccd_turn__wrap_up', recap: 'x' } as any))
  await settle()
  expect(seen.compacts).toBe(0)
  const ui = await $.ui.mount({ ...BAND, surface: 'desktop' } as any)
  expect((await ui.find({ type: 'Text', text: /good moment to compact/ }))?.text).toContain('task wrapped up')
  await ui.unmount()
  seen.release()               // idle_minutes pass with no new turn
  await settle()
  expect(seen.compacts).toBe(1)
})

test('on a 1M window a commit at 250k tokens compacts right away, a calm stop is offered', async ($, on) => {
  const seen = engine(on, 25, { cfg: {} })
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
  await turn($, () => $.tool.call({ tool: 'Read', file_path: 'C:/a.ts' } as any))
  await settle()
  expect(seen.compacts).toBe(0)   // nothing finished: an offer, not a compaction
  const ui = await $.ui.mount({ ...BAND, surface: 'desktop' } as any)
  expect((await ui.find({ type: 'Text', text: /good moment to compact/ }))?.text).toContain('a calm point')
  await ui.unmount()
  await turn($, () => $.tool.call({ tool: 'Bash', command: 'git commit -m x' } as any))
  await settle()
  expect(seen.compacts).toBe(1)
})

test('on a 1M window 420k tokens compacts at the turn end even mid-task', async ($, on) => {
  const seen = engine(on, 42, { cfg: {} })
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
  await turn($, () => $.tool.call({ tool: 'Bash', command: 'npm test' } as any))   // fails: an open failure
  await settle()
  expect(seen.compacts).toBe(1)
})

test('below 100k tokens a finished task is left alone', async ($, on) => {
  const seen = engine(on, 8, { cfg: {} })
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
  await turn($, () => $.tool.call({ tool: 'mcp__ccd_turn__wrap_up', recap: 'x' } as any))
  await settle()
  seen.release()
  await settle()
  expect(seen.compacts).toBe(0)
  const ui = await $.ui.mount({ ...BAND, surface: 'desktop' } as any)
  expect(await ui.find({ type: 'Text', text: /good moment/ })).toBeUndefined()
  await ui.unmount()
})

test('Cairn Home is compacted from 50k tokens, not from 15% of a 1M window', async ($, on) => {
  const seen = engine(on, 6, { cfg: {}, cwd: 'C:/Users/me/.claude/cairn/home' })   // 60k tokens
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
  await turn($, () => $.tool.call({ tool: 'mcp__ccd_turn__wrap_up', recap: 'x' } as any))
  await settle()
  const ui = await $.ui.mount({ ...BAND, surface: 'desktop' } as any)
  expect(await ui.find({ type: 'Text', text: /good moment to compact/ })).toBeDefined()
  await ui.unmount()
})
