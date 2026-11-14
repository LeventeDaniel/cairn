import { expect, test } from 'claude-code/testing'

const PANE = {
  plugin: 'cairn',
  component: 'Pane',
  requestId: 'cairn',
  props: {
    title: 'Cairn',
    isFocused: false,
    bodyColumns: 80,
    placement: 'dock',
    scroll: { offset: 0, bodyRows: 40 },
    view: {},
  },
} as const

const WS = {
  at: 1, cacheTtlMin: 60,
  repos: [
    { name: 'example-a', path: 'C:/r/a', purpose: 'kit', goal: 'Ship the workspace view', next: '', notes: 1, worktrees: 0,
      sessions: [{ id: 'a', title: 'cairn: workspace', status: 'busy', ageMin: 0, tokens: 120000, warm: true }] },
    { name: 'example-b', path: 'C:/r/b', purpose: 'worker', goal: '', next: '', notes: 0, worktrees: 2,
      sessions: [{ id: 'b', title: 'fix login page', status: 'closed', ageMin: 300, tokens: 90000, warm: false }] },
  ],
  unregistered: [],
  board: [
    { id: 't2', repo: 'example-b', title: 'example-b: fix export', kind: 'normal', model: 'sonnet', effort: 'medium',
      session: 'local_x', status: 'waiting', started: 1, updated: 1, report: 'needs your review' },
    { id: 't3', repo: 'example-a', title: 'example-a: new header', kind: 'small', model: 'sonnet', effort: 'low',
      session: 'local_y', status: 'running', started: 2, updated: 2, report: '' },
    { id: 't1', repo: 'example-a', title: 'example-a: old task', kind: 'small', model: 'sonnet', effort: 'low',
      session: 'local_z', status: 'done', started: 0, updated: 0, report: 'committed' },
  ],
}

const afters: number[] = []

function engine(on: any, settings: Record<string, unknown>, long = { n: 0 }) {
  const runs: string[][] = []
  on('command.register', () => ({ value: { command: 'cairn' } }))
  on('ui.open', () => ({ value: { isPlaced: true } }))
  on('session.start', (_: any, e: any) => ({ cwd: e.cwd }))
  on('session.id', () => ({ value: 's1' }))
  on('session.usage', () => ({ value: { startedAt: 0, context: { tokens: 100000, window: 1000000, percent: 10 }, rateLimits: [], cost: { usd: 2.5 } } }))
  on('settings.read', (_: any, e: any) => ({ value: e?.key ? settings[e.key] : settings }))
  on('process.run', (_: any, e: any) => { runs.push([...e.argv]); return { value: { exitCode: 0, stdout: JSON.stringify(WS), stderr: '' } } })
  on('fs.read', () => ({ value: '{}' }))
  on('fs.list', () => ({ value: [] }))
  on('fs.write', () => ({ value: undefined }))
  on('store.get', () => ({ value: undefined }))
  on('store.set', () => ({ value: undefined }))
  on('ui.toast', () => ({ value: undefined }))
  on('ui.status', () => ({ value: undefined }))
  on('ui.log', () => ({ value: undefined }))
  on('clock.now', () => ({ value: 1000 }))
  on('turn.start', (_: any, e: any) => ({ turnId: e.turnId }))
  on('turn.complete', (_: any, e: any) => ({ text: e.answer }))
  on('session.measure', (_: any, e: any) => ({ changed: e.changed }))
  on('clock.after', (_: any, e: any) => { afters.push(e.ms); if (e.ms >= 30 * 60000) long.n++; return { value: undefined } })
  return runs
}

const settle = async () => { for (let i = 0; i < 300; i++) await Promise.resolve() }

const HOOKS = {
  UserPromptSubmit: [{ hooks: [{ type: 'command', command: 'C:/Py/python.exe C:/Users/me/.claude/cairn/cairn.py prompt' }] }],
}

test('the pane shows every repo from cairn.py workspace, run with the hook\'s own python', async ($, on) => {
  const runs = engine(on, { hooks: HOOKS })
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
  await settle()
  expect(runs[0]).toEqual(['C:/Py/python.exe', 'C:/Users/me/.claude/cairn/cairn.py', 'workspace', '--json'])
  const ui = await $.ui.mount({ ...PANE, surface: 'desktop' } as any)
  expect((await ui.find({ type: 'Text', text: /example-a/ }))?.text).toContain('1 note(s) waiting')
  expect((await ui.find({ type: 'Text', text: /Ship the workspace/ }))).toBeTruthy()
  expect((await ui.find({ type: 'Text', text: /cairn: workspace/ }))?.text).toContain('cache warm')
  expect((await ui.find({ type: 'Text', text: /example-b/ }))?.text).toContain('2 worktree(s)')
  expect((await ui.find({ type: 'Text', text: /no live session/ }))?.text).toContain('5 h ago')
  await ui.unmount()
})

test('without a Cairn hook the workspace stays empty and nothing runs', async ($, on) => {
  const runs = engine(on, { hooks: {} })
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
  await settle()
  expect(runs.length).toBe(0)
  const ui = await $.ui.mount({ ...PANE, surface: 'desktop' } as any)
  expect((await ui.find({ type: 'Text', text: /Loading/ }))).toBeTruthy()
  await ui.unmount()
})

test('a 5-minute cache TTL from settings turns the idle cache guard off', async ($, on) => {
  const long = { n: 0 }
  engine(on, { hooks: HOOKS, promptCacheTtl: '5m' }, long)
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
  await $.turn.start({ turnId: 't', text: 'go' } as any)
  await $.turn.complete({ turnId: 't', reason: 'answer', answer: 'done', durationMs: 1, isAborted: false } as any)
  await settle()
  expect(long.n).toBe(0)
})

test('with the default TTL the guard is armed at each turn end', async ($, on) => {
  const long = { n: 0 }
  engine(on, { hooks: HOOKS }, long)
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
  await $.turn.start({ turnId: 't', text: 'go' } as any)
  await $.turn.complete({ turnId: 't', reason: 'answer', answer: 'done', durationMs: 1, isAborted: false } as any)
  await settle()
  expect(long.n).toBe(1)
})

test("the pane shows Cairn Home's board: waiting, running and recent done rows", async ($, on) => {
  engine(on, { hooks: HOOKS })
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
  await settle()
  const ui = await $.ui.mount({ ...PANE, surface: 'desktop' } as any)
  expect((await ui.find({ type: 'Text', text: /Board \(Cairn Home\)/ }))?.text).toContain('1 running · 1 waiting on you')
  expect((await ui.find({ type: 'Text', text: /t2 example-b: fix export/ }))?.text).toContain('needs your review')
  expect((await ui.find({ type: 'Text', text: /t1 example-a: old task/ }))?.text).toContain('done')
  await ui.unmount()
})

test('an idle session re-reads the workspace every 2 minutes so the board does not go stale', async ($, on) => {
  afters.length = 0
  engine(on, { hooks: HOOKS })
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
  await settle()
  expect(afters).toContain(120000)
})

test('the pane adds up cost per day and shows peak plan usage', async ($, on) => {
  engine(on, { hooks: HOOKS })
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
  await $.turn.start({ turnId: 't', text: 'go' } as any)
  await $.turn.complete({ turnId: 't', reason: 'answer', answer: 'done', durationMs: 1, isAborted: false } as any)
  await settle()
  const ui = await $.ui.mount({ ...PANE, surface: 'desktop' } as any)
  expect((await ui.find({ type: 'Text', text: /01-01 \$2\.50/ }))?.text).toContain('1 sessions')
  await ui.unmount()
})
