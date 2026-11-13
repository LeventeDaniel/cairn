import { expect, test } from 'claude-code/testing'

const PANE = {
  plugin: 'cairn',
  component: 'Pane',
  requestId: 'cairn',
  props: {
    title: 'Cairn',
    isFocused: false,
    bodyColumns: 50,
    placement: 'dock',
    scroll: { offset: 0, bodyRows: 20 },
    view: {},
  },
} as const

test('a measure past warn draws the pane, toasts and feeds cairn.py state', async ($, on) => {
  const writes: { path: string; text: string }[] = []
  const toasts: string[] = []
  on('command.register', () => ({ value: { command: 'cairn' } }))
  on('ui.open', () => ({ value: { isPlaced: true } }))
  on('session.start', (_, e) => ({ cwd: e.cwd }))
  on('session.id', () => ({ value: 'abc-123:x' }))
  on('session.usage', () => ({ value: { startedAt: 0, context: { window: 1000000 }, rateLimits: [] } }))
  on('fs.read', () => ({ value: JSON.stringify({ warn: 50, urgent: 70 }) }))
  on('fs.list', () => ({ value: [{ name: 'billing.md', kind: 'file', size: 42, mtimeMs: 0, isLink: false }] }))
  on('fs.write', (_, e) => { writes.push(e); return { value: undefined } })
  on('ui.toast', (_, e) => { toasts.push(e.text); return { value: undefined } })
  on('session.measure', (_, e) => ({ changed: e.changed }))
  on('clock.now', () => ({ value: 1000 }))
  on('ui.status', () => ({ value: undefined }))
  on('ui.log', () => ({ value: undefined }))

  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
  await $.session.measure({
    context: { tokens: 550000, window: 1000000, percent: 55 },
    rateLimits: [{ kind: 'five_hour', percentUsed: 12 }, { kind: 'seven_day', percentUsed: 40 }],
    cost: { usd: 3.5 },
    changed: ['context'],
  })

  for (const surface of ['terminal', 'desktop'] as const) {
    const ui = await $.ui.mount({ ...PANE, surface })
    expect((await ui.find({ type: 'Text', text: /55%/ }))?.text).toContain('55%')
    expect((await ui.find({ type: 'Text', text: /5h 12%/ }))?.text).toContain('7d 40%')
    expect((await ui.find({ type: 'Text', text: /billing/ }))?.text).toContain('billing')
    expect((await ui.find({ type: 'Text', text: /next clean break/ }))).toBeTruthy()
    await ui.unmount()
  }

  expect(toasts.some(t => t.includes('55%'))).toBe(false) // smart mode speaks through its decisions
  const fwd = writes.map(w => ({ ...w, path: w.path.split(String.fromCharCode(92)).join('/') }))
  const state = fwd.filter(w => w.path.endsWith('/cairn/state/abc-123x.json')).at(-1)
  expect(state).toBeTruthy()
  expect(JSON.parse(state!.text).pct).toBe(55)
  expect(JSON.parse(state!.text).five_hour).toBe(12)
  expect(fwd.some(w => w.path.endsWith('/cairn/state/last.json'))).toBe(true)
})
