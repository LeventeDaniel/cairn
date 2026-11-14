import { expect, test } from 'claude-code/testing'

const BAND = {
  plugin: 'cairn',
  component: 'AbovePrompt',
  props: {
    hasSurvey: false, isCollapsed: false, isWorking: false, bodyColumns: 100, maxRows: 4,
    scroll: { offset: 0, bodyRows: 3 }, view: {},
  },
} as const

type Seen = { compacts: number; toasts: string[]; release: () => void; releaseCache: () => void; stored: Record<string, unknown> }

/** An engine at `percent` context; long timers (the idle one) wait for `seen.release()`. */
function engine(on: any, percent: number, opt: { now?: number; ends?: unknown; cwd?: string; failCompact?: boolean } = {}): Seen {
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
  on('fs.read', () => ({ value: '{}' }))
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
  await settle()
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

test('a big session resumed after the cache expired compacts by itself, no click', async ($, on) => {
  const seen = engine(on, 20, { now: 3 * 3600000, ends: { s1: { at: 0, tokens: 200000 } } })
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
  await settle()
  expect(seen.compacts).toBe(1)
  expect(seen.toasts.some(t => t.includes('away 3 h'))).toBe(true)
})

test('if the idle compaction cannot run, the banner stays as the fallback', async ($, on) => {
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
