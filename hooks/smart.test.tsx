import { expect, test } from 'claude-code/testing'

const BAND = {
  plugin: 'coach-watcher',
  component: 'AbovePrompt',
  props: {
    hasSurvey: false, isCollapsed: false, isWorking: false, bodyColumns: 100, maxRows: 4,
    scroll: { offset: 0, bodyRows: 3 }, view: {},
  },
} as const

type Seen = { compacts: number; toasts: string[]; release: () => void }

/** An engine at `percent` context; long timers (the idle one) wait for `seen.release()`. */
function engine(on: any, percent: number): Seen {
  const seen: Seen = { compacts: 0, toasts: [], release: () => {} }
  const gate = new Promise<void>(r => { seen.release = r })
  on('command.register', () => ({ value: { command: 'coach' } }))
  on('ui.open', () => ({ value: { isPlaced: true } }))
  on('session.start', (_: any, e: any) => ({ cwd: e.cwd }))
  on('session.id', () => ({ value: 's1' }))
  on('session.usage', () => ({ value: {
    startedAt: 0, context: { tokens: percent * 10000, window: 1000000, percent }, rateLimits: [] } }))
  on('fs.read', () => ({ value: '{}' }))
  on('fs.list', () => ({ value: [] }))
  on('fs.write', () => ({ value: undefined }))
  on('ui.toast', (_: any, e: any) => { seen.toasts.push(e.text); return { value: undefined } })
  on('ui.status', () => ({ value: undefined }))
  on('ui.log', () => ({ value: undefined }))
  on('clock.now', () => ({ value: 1000 }))
  on('clock.after', async (_: any, e: any) => { if (e.ms > 10000) await gate; return { value: undefined } })
  on('tool.call', (_: any, e: any) =>
    e.tool === 'Bash' && e.command === 'npm test' && !(globalThis as any).__pass
      ? { isError: true, result: 'FAIL', text: 'FAIL a.test.ts' }
      : { result: {}, text: 'ok' })
  on('turn.start', (_: any, e: any) => ({ turnId: e.turnId }))
  on('turn.complete', (_: any, e: any) => ({ text: e.answer }))
  on('session.measure', (_: any, e: any) => ({ changed: e.changed }))
  on('command.run', (_: any, e: any) => {
    if (e.command === 'compact') seen.compacts++
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
