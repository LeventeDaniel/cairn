import { expect, test } from 'claude-code/testing'

// Cairn never asks about a compaction (no band, no buttons). What it plans shows as one line in the pane.
const PANE = {
  plugin: 'cairn',
  component: 'Pane',
  requestId: 'cairn',
  props: {
    title: 'Cairn', isFocused: false, bodyColumns: 100, placement: 'dock',
    scroll: { offset: 0, bodyRows: 20 }, view: {},
  },
} as const
const PLANNED = /compacts this chat if you stay away/

const PCT_ONLY = {
  compact_soft_tokens: 0, compact_at_tokens: 0, compact_hard_tokens: 0,
  home_compact_soft_tokens: 0, home_compact_at_tokens: 0, home_compact_hard_tokens: 0,
}

type Seen = { compacts: number; toasts: string[]; writes: string[]; release: () => void; releaseCache: () => void; stored: Record<string, unknown> }

/** An engine at `percent` context; long timers (the idle one) wait for `seen.release()`. */
function engine(on: any, percent: number, opt: { now?: number; ends?: unknown; cwd?: string; failCompact?: boolean; board?: unknown; cfg?: object
  floor?: unknown; limits?: unknown[]; measured?: unknown } = {}): Seen {
  const seen: Seen = { compacts: 0, toasts: [], writes: [], release: () => {}, releaseCache: () => {}, stored: {} }
  const gate = new Promise<void>(r => { seen.release = r })
  const cacheGate = new Promise<void>(r => { seen.releaseCache = r })
  if (opt.ends) seen.stored.lastEnd = opt.ends
  if (opt.floor) seen.stored.floor = opt.floor
  on('store.get', (_: any, e: any) => ({ value: seen.stored[e.key] }))
  on('store.set', (_: any, e: any) => { seen.stored[e.key] = e.value; return { value: undefined } })
  on('command.register', () => ({ value: { command: 'cairn' } }))
  on('ui.open', () => ({ value: { isPlaced: true } }))
  on('session.start', (_: any, e: any) => ({ cwd: e.cwd }))
  on('session.id', () => ({ value: 's1' }))
  on('session.cwd', () => ({ value: opt.cwd ?? 'C:/r/example-a' }))
  on('session.usage', () => ({ value: {
    startedAt: 0, context: { tokens: percent * 10000, window: 1000000, percent }, rateLimits: opt.limits ?? [] } }))
  // These tests are about the percentage steps (the test window is 1M tokens, so 50% is 500k): the token
  // steps are switched off unless a test passes its own config.
  const config = JSON.stringify(opt.cfg ?? PCT_ONLY)
  on('fs.read', (_: any, e: any) => ({ value: opt.board && String(e.path).endsWith('board.json') ? JSON.stringify(opt.board)
    : String(e.path).endsWith('config.json') ? config
    : opt.measured && String(e.path).endsWith('measured.json') ? JSON.stringify(opt.measured) : '{}' }))
  on('fs.list', () => ({ value: [] }))
  on('fs.write', (_: any, e: any) => { seen.writes.push(`${e.path} ${e.text}`); return { value: undefined } })
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

test('a finished task at 50% is not asked about: one pane line, then it runs if nobody comes back', async ($, on) => {
  const seen = engine(on, 50)
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
  await turn($, () => $.tool.call({ tool: 'mcp__ccd_turn__wrap_up', recap: 'x' } as any))
  await settle()
  expect(seen.compacts).toBe(0)
  expect(seen.toasts.length).toBe(0)

  const ui = await $.ui.mount({ ...PANE, surface: 'desktop' } as any)
  expect((await ui.find({ type: 'Text', text: PLANNED }))?.text).toContain('task wrapped up')
  expect(await ui.find({ type: 'Button', text: /Compact now|Not now|OK/ })).toBeUndefined()
  seen.release()               // idle_minutes pass with no new turn
  await settle()
  expect(seen.compacts).toBe(1)
  expect(await ui.find({ type: 'Text', text: PLANNED })).toBeUndefined()
  await ui.unmount()
  // one line about it, after the fact
  expect(seen.toasts.length).toBe(1)
  expect(seen.toasts[0]).toContain('Cairn compacted this chat: task wrapped up')
})

test('a calm turn end at 50% with nothing finished just waits', async ($, on) => {
  const seen = engine(on, 50)
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
  await turn($, () => $.tool.call({ tool: 'Read', file_path: 'C:/a.ts' } as any))
  await settle()
  const ui = await $.ui.mount({ ...PANE, surface: 'terminal' } as any)
  expect(await ui.find({ type: 'Text', text: PLANNED })).toBeUndefined()
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

test('a calm stop past compact_at is compacted once the person has been away', async ($, on) => {
  const seen = engine(on, 62)
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
  await turn($, () => $.tool.call({ tool: 'Read', file_path: 'C:/a.ts' } as any))
  await settle()
  expect(seen.compacts).toBe(0)
  seen.release()               // idle_minutes pass with no new turn
  await settle()
  expect(seen.compacts).toBe(1)
  expect(seen.toasts.some(t => t.includes('you were away 3 min'))).toBe(true)
})

test('a new prompt calls off a planned compaction: the person is back', async ($, on) => {
  const seen = engine(on, 62)
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
  await turn($, () => $.tool.call({ tool: 'Read', file_path: 'C:/a.ts' } as any))
  await settle()
  const ui = await $.ui.mount({ ...PANE, surface: 'desktop' } as any)
  expect(await ui.find({ type: 'Text', text: PLANNED })).toBeDefined()
  await $.turn.start({ turnId: 't2', text: 'next thing' } as any)   // before the idle minutes are over
  await settle()
  expect(await ui.find({ type: 'Text', text: PLANNED })).toBeUndefined()
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
  const ui = await $.ui.mount({ ...PANE, surface: 'desktop' } as any)
  expect(await ui.find({ type: 'Text', text: PLANNED })).toBeUndefined()
  await ui.unmount()
})

test('a failure left from an earlier turn does not block the compaction once the task is wrapped up', async ($, on) => {
  const seen = engine(on, 50)
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
  await turn($, () => $.tool.call({ tool: 'Bash', command: 'npm test' } as any))
  await settle()
  await turn($, () => $.tool.call({ tool: 'mcp__ccd_turn__wrap_up', recap: 'x' } as any))
  await settle()
  const ui = await $.ui.mount({ ...PANE, surface: 'desktop' } as any)
  expect((await ui.find({ type: 'Text', text: PLANNED }))?.text).toContain('task wrapped up')
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

test('each turn end is noted, so a later start can tell the cache went cold', async ($, on) => {
  const seen = engine(on, 20)
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
  await turn($, () => $.tool.call({ tool: 'Read', file_path: 'C:/a.ts' } as any))
  await settle()
  expect((seen.stored.lastEnd as any).s1).toEqual({ at: 1000, tokens: 200000 })
})

test('a big session started after the cache expired is neither compacted nor asked about', async ($, on) => {
  // An app restart starts every open session at once; compacting them all on a cold cache is a full-price
  // read each (this took a quarter of a 5-hour limit in seconds). And Cairn does not ask: the first reply
  // runs on the full context, and the turn end after it is an ordinary one.
  const seen = engine(on, 20, { now: 3 * 3600000, ends: { s1: { at: 0, tokens: 200000 } } })
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
  for (let i = 0; i < 5; i++) await settle()
  seen.release(); seen.releaseCache()
  for (let i = 0; i < 5; i++) await settle()
  expect(seen.compacts).toBe(0)
  expect(seen.toasts.length).toBe(0)
  const ui = await $.ui.mount({ ...PANE, surface: 'desktop' } as any)
  expect(await ui.find({ type: 'Text', text: /compact/i })).toBeUndefined()
  expect(await ui.find({ type: 'Button', text: /Compact now|Not now/ })).toBeUndefined()
  await ui.unmount()
  expect(seen.writes.some(w => w.includes('cache-warning'))).toBe(false)   // nobody came back yet
  await turn($, () => $.tool.call({ tool: 'Read', file_path: 'C:/a.ts' } as any))
  await settle()
  // the reply that really re-read 200k tokens at full price is on record, for the results
  expect(seen.writes.some(w => w.includes('"cache-warning"') && w.includes('"cold"') && w.includes('200000'))).toBe(true)
})

test('a config that still says ask is treated as smart: nothing is asked', async ($, on) => {
  const seen = engine(on, 62, { cfg: { ...PCT_ONLY, compact_mode: 'ask' } })
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
  await turn($, () => $.tool.call({ tool: 'Bash', command: 'git commit -m "x"' } as any))
  await settle()
  expect(seen.compacts).toBe(1)
})

test('a session resumed while the cache is still warm gets no note', async ($, on) => {
  engine(on, 20, { now: 30 * 60000, ends: { s1: { at: 0, tokens: 200000 } } })
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
  await settle()
  const ui = await $.ui.mount({ ...PANE, surface: 'desktop' } as any)
  expect(await ui.find({ type: 'Text', text: /compact/i })).toBeUndefined()
  await ui.unmount()
})

test('in Cairn Home a wrapped-up turn at 20% is already planned (home thresholds)', async ($, on) => {
  engine(on, 20, { cwd: String.raw`C:\Users\me\.claude\cairn\home` })
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
  await turn($, () => $.tool.call({ tool: 'mcp__ccd_turn__wrap_up', recap: 'x' } as any))
  await settle()
  const ui = await $.ui.mount({ ...PANE, surface: 'desktop' } as any)
  expect((await ui.find({ type: 'Text', text: PLANNED }))).toBeTruthy()
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
  const ui = await $.ui.mount({ ...PANE, surface: 'desktop' } as any)
  expect((await ui.find({ type: 'Text', text: PLANNED }))).toBeFalsy()
  expect(seen.compacts).toBe(0)
  await ui.unmount()
})

// A worker whose board task is finished gets no more messages: compacting it while idle only spends plan usage.
const DONE_BOARD = { tasks: [{ id: 't1', cliSession: 's1', status: 'done' }] }

test('a finished worker is not compacted while it sits idle', async ($, on) => {
  const seen = engine(on, 62, { board: DONE_BOARD })
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
  await turn($, () => $.tool.call({ tool: 'Read', file_path: 'C:/a.ts' } as any))
  await settle()
  seen.release(); seen.releaseCache()   // the idle minutes and the cache guard both pass
  for (let i = 0; i < 5; i++) await settle()
  expect(seen.compacts).toBe(0)
  const ui = await $.ui.mount({ ...PANE, surface: 'desktop' } as any)
  expect(await ui.find({ type: 'Text', text: PLANNED })).toBeUndefined()   // and the pane no longer says it will
  await ui.unmount()
})

// Seen live: a finished 195k-token worker was compacted at restart, and the whole history was read
// uncached for a session nobody would use again.
test('a finished worker reopened after the cache expired: the pane says to archive it, nothing is compacted', async ($, on) => {
  const seen = engine(on, 20, { now: 3 * 3600000, ends: { s1: { at: 0, tokens: 200000 } }, board: DONE_BOARD })
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
  for (let i = 0; i < 5; i++) await settle()
  expect(seen.compacts).toBe(0)
  const ui = await $.ui.mount({ ...PANE, surface: 'desktop' } as any)
  expect((await ui.find({ type: 'Text', text: /task is finished: archive it/ }))?.text).toContain('200k tokens')
  expect(await ui.find({ type: 'Text', text: PLANNED })).toBeUndefined()
  expect(await ui.find({ type: 'Button', text: /Compact now|Not now|OK/ })).toBeUndefined()
  seen.release(); seen.releaseCache()
  for (let i = 0; i < 5; i++) await settle()
  expect(seen.compacts).toBe(0)
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
test('on a 1M window a finished task at 150k tokens is planned, and runs if nobody comes back', async ($, on) => {
  const seen = engine(on, 15, { cfg: {} })   // 150k of 1M: 15%, far below compact_soft 40%
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
  await turn($, () => $.tool.call({ tool: 'mcp__ccd_turn__wrap_up', recap: 'x' } as any))
  await settle()
  expect(seen.compacts).toBe(0)
  const ui = await $.ui.mount({ ...PANE, surface: 'desktop' } as any)
  expect((await ui.find({ type: 'Text', text: PLANNED }))?.text).toContain('task wrapped up')
  await ui.unmount()
  seen.release()               // idle_minutes pass with no new turn
  await settle()
  expect(seen.compacts).toBe(1)
})

test('on a 1M window a commit at 250k tokens compacts right away, a calm stop waits for the person to be away', async ($, on) => {
  const seen = engine(on, 25, { cfg: {} })
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
  await turn($, () => $.tool.call({ tool: 'Read', file_path: 'C:/a.ts' } as any))
  await settle()
  expect(seen.compacts).toBe(0)   // nothing finished: only if the person stays away
  const ui = await $.ui.mount({ ...PANE, surface: 'desktop' } as any)
  expect((await ui.find({ type: 'Text', text: PLANNED }))?.text).toContain('a calm point')
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
  const ui = await $.ui.mount({ ...PANE, surface: 'desktop' } as any)
  expect(await ui.find({ type: 'Text', text: PLANNED })).toBeUndefined()
  await ui.unmount()
})

test('Cairn Home is compacted from 50k tokens, not from 15% of a 1M window', async ($, on) => {
  const seen = engine(on, 6, { cfg: {}, cwd: 'C:/Users/me/.claude/cairn/home' })   // 60k tokens
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
  await turn($, () => $.tool.call({ tool: 'mcp__ccd_turn__wrap_up', recap: 'x' } as any))
  await settle()
  const ui = await $.ui.mount({ ...PANE, surface: 'desktop' } as any)
  expect(await ui.find({ type: 'Text', text: PLANNED })).toBeDefined()
  await ui.unmount()
})

// ---- the floor: a compaction cannot go below what every context restarts at (system prompt, tools, summary)
// Measured 2026-11-15: the engine reported 95k -> 16k, the next reply ran at 85k. Home's steps sat under it.
const HOME = 'C:/Users/me/.claude/cairn/home'

test('with an 85k floor known, Cairn Home at 95k is left alone: there is 10k to remove, not 79k', async ($, on) => {
  const seen = engine(on, 9.5, { cfg: {}, cwd: HOME, floor: { home: [85000, 91000] } })
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
  await turn($, () => $.tool.call({ tool: 'mcp__ccd_turn__wrap_up', recap: 'x' } as any))
  await settle()
  seen.release(); seen.releaseCache()
  for (let i = 0; i < 5; i++) await settle()
  expect(seen.compacts).toBe(0)
  const ui = await $.ui.mount({ ...PANE, surface: 'desktop' } as any)
  expect(await ui.find({ type: 'Text', text: PLANNED })).toBeUndefined()
  await ui.unmount()
})

// Counted 2026-11-15: a compaction must remove ~100k to earn back the cache it re-writes within ~10 replies.
test('with an 85k floor, Cairn Home at 150k is left alone: 65k removed does not pay for the cache re-write', async ($, on) => {
  const seen = engine(on, 15, { cfg: {}, cwd: HOME, floor: { home: [85000] } })
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
  await turn($, () => $.tool.call({ tool: 'mcp__ccd_turn__wrap_up', recap: 'x' } as any))
  await settle()
  expect(seen.compacts).toBe(0)
  const ui = await $.ui.mount({ ...PANE, surface: 'desktop' } as any)
  expect(await ui.find({ type: 'Text', text: PLANNED })).toBeUndefined()
  await ui.unmount()
})

test('with an 85k floor, Cairn Home plans a compaction from floor + 100k and compacts mid-task from floor + 200k', async ($, on) => {
  const seen = engine(on, 19, { cfg: {}, cwd: HOME, floor: { home: [85000] } })   // 190k: past 185k
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
  await turn($, () => $.tool.call({ tool: 'mcp__ccd_turn__wrap_up', recap: 'x' } as any))
  await settle()
  expect(seen.compacts).toBe(0)
  const ui = await $.ui.mount({ ...PANE, surface: 'desktop' } as any)
  expect(await ui.find({ type: 'Text', text: PLANNED })).toBeDefined()
  await ui.unmount()
})

test('with an 85k floor, Cairn Home at 290k compacts at the turn end, mid-task or not', async ($, on) => {
  const seen = engine(on, 29, { cfg: {}, cwd: HOME, floor: { home: [85000] } })
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
  await turn($, () => $.tool.call({ tool: 'Read', file_path: 'C:/a.ts' } as any))
  await settle()
  expect(seen.compacts).toBe(1)
})

test('a floor learned in a repo does not move Home, and the measured file stands in until one is learned', async ($, on) => {
  const seen = engine(on, 12, { cfg: {}, floor: { home: [85000] }, measured: { history: { floor: 80000 } } })   // a repo at 120k
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
  await turn($, () => $.tool.call({ tool: 'mcp__ccd_turn__wrap_up', recap: 'x' } as any))
  await settle()
  const ui = await $.ui.mount({ ...PANE, surface: 'desktop' } as any)
  expect(await ui.find({ type: 'Text', text: PLANNED })).toBeUndefined()   // 120k is under 80k + 60k
  await ui.unmount()
  expect(seen.compacts).toBe(0)
})

test('the first reading of the turn after a compaction is kept as the floor', async ($, on) => {
  const seen = engine(on, 30, { cfg: {} })
  on('session.compact', () => ({ messages: [{ role: 'user', text: 's', toolUses: [] }], tokensBefore: 300000, tokensAfter: 16000 }))
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
  await $.session.compact({ trigger: 'manual', messages: [{ role: 'user', text: 'hi', toolUses: [] }] } as any)
  const reading = (tokens: number) => $.session.measure({
    startedAt: 0, context: { tokens, window: 1000000, percent: tokens / 10000 }, rateLimits: [], changed: [] } as any)
  await reading(16000)                       // before any new turn: the engine's own count, not the floor
  expect(seen.stored.floor).toBeUndefined()
  await $.turn.start({ turnId: 't2', text: 'go' } as any)
  await reading(87000)
  await reading(120000)                      // later readings of the same turn are the turn's own work
  expect(seen.stored.floor).toEqual({ work: [87000] })
})

// ---- the plan limit: at the limit a compaction can only fail, just under it, it spends what is left
const SPENT = [{ kind: 'five_hour', percentUsed: 97 }, { kind: 'seven_day', percentUsed: 40 }]

test('with the 5-hour limit nearly used up nothing is compacted by Cairn itself', async ($, on) => {
  const seen = engine(on, 75, { limits: SPENT })   // past the hard step: would compact at the turn end
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
  await turn($, () => $.tool.call({ tool: 'Bash', command: 'git commit -m x' } as any))
  await settle()
  seen.release(); seen.releaseCache()
  for (let i = 0; i < 5; i++) await settle()
  expect(seen.compacts).toBe(0)
})

test('with the limit nearly used up, /cairn compact still runs: the person asked', async ($, on) => {
  const seen = engine(on, 75, { limits: SPENT })
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
  await $.command.run({ command: 'cairn', args: 'compact' } as any)
  await settle()
  expect(seen.compacts).toBe(1)
})
