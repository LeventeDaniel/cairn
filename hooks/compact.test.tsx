import { expect, test } from 'claude-code/testing'

const PANE = {
  plugin: 'coach-watcher',
  component: 'Pane',
  requestId: 'coach-watcher',
  props: {
    title: 'Context Coach', isFocused: false, bodyColumns: 60, placement: 'dock',
    scroll: { offset: 0, bodyRows: 40 }, view: {},
  },
} as const

const BIG = 'x'.repeat(20000)

function engine(on: any, seen: { compact?: any }, opts: { summary: string; refuseTrim?: boolean }) {
  on('command.register', () => ({ value: { command: 'coach' } }))
  on('ui.open', () => ({ value: { isPlaced: true } }))
  on('session.start', (_: any, e: any) => ({ cwd: e.cwd }))
  on('session.id', () => ({ value: 's1' }))
  on('session.usage', () => ({ value: { startedAt: 0, context: { window: 1000000 }, rateLimits: [] } }))
  on('fs.read', (_: any, e: any) => {
    if (String(e.path).endsWith('SESSION.md')) return { value: '## Goal\nShip the coach watcher\n## Next\n1. test it\n' }
    return { value: '{}' }
  })
  on('fs.list', () => ({ value: [] }))
  on('fs.write', () => ({ value: undefined }))
  on('ui.toast', () => ({ value: undefined }))
  on('ui.status', () => ({ value: undefined }))
  on('ui.log', () => ({ value: undefined }))
  on('clock.now', () => ({ value: 1000 }))
  on('tool.call', (_: any, e: any) =>
    e.tool === 'Bash' && e.command === 'npm test'
      ? { isError: true, result: 'FAIL', text: 'FAIL src/a.test.ts\nExpected 1 got 2' }
      : { result: {}, text: 'ok' })
  on('session.compact', (_: any, e: any) => {
    seen.compact = e
    if (opts.refuseTrim && e.messages.some((m: any) => !m.handle)) throw new Error('refused')
    return { messages: [{ role: 'user', text: opts.summary, toolUses: [] }], tokensBefore: 600000, tokensAfter: 40000 }
  })
}

const TRANSCRIPT = [
  { role: 'user', text: 'Make compaction smarter', toolUses: [], handle: 'h1' },
  { role: 'assistant', text: '', toolUses: [{ tool_use_id: 't1', tool: 'Read', input: { file_path: 'C:/big.log' } }], handle: 'h2' },
  { role: 'user', text: '', toolUses: [], toolResults: [{ tool_use_id: 't1', text: BIG, isError: false }], handle: 'h3' },
]

test('compaction gets Coach notes, trimmed results, and a patched summary', async ($, on) => {
  const seen: { compact?: any } = {}
  engine(on, seen, { summary: 'We worked on things.' })
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
  await $.tool.call({ tool: 'Edit', file_path: 'C:/repo/hooks/register.tsx', old_string: 'a', new_string: 'b' })
  await $.tool.call({ tool: 'Bash', command: 'npm test' })

  const res: any = await $.session.compact({ trigger: 'manual', instructions: 'focus on the mod', messages: TRANSCRIPT } as any)

  const sent = seen.compact
  expect(sent.instructions).toContain('focus on the mod')
  expect(sent.instructions).toContain('Ship the coach watcher')
  expect(sent.instructions).toContain('register.tsx')
  expect(sent.instructions).toContain('npm test')
  expect(sent.instructions).toContain('Make compaction smarter')
  const trimmed = sent.messages[2].toolResults[0].text
  expect(trimmed.length < 2000).toBe(true)
  expect(trimmed).toContain('Context Coach trimmed')
  expect(trimmed).toContain('C:/big.log')
  expect(sent.messages[0].handle).toBe('h1')

  // The summary forgot register.tsx, so Coach patched the state into it.
  expect(res.messages[0].text).toContain('State carried across this compaction')
  expect(res.messages[0].text).toContain('register.tsx')

  for (const surface of ['terminal', 'desktop'] as const) {
    const ui = await $.ui.mount({ ...PANE, surface })
    expect((await ui.find({ type: 'Text', text: /600k → 40k/ }))?.text).toContain('check patched')
    expect((await ui.find({ type: 'Text', text: /Open failures/ }))?.text).toContain('npm test')
    await ui.unmount()
  }
})

test('a summary that kept the files is left alone; a passing rerun clears the failure', async ($, on) => {
  const seen: { compact?: any } = {}
  engine(on, seen, { summary: 'Edited register.tsx; tests next.' })
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
  await $.tool.call({ tool: 'Write', file_path: 'C:/repo/hooks/register.tsx', content: 'x' })

  const res: any = await $.session.compact({ trigger: 'manual', messages: TRANSCRIPT } as any)
  expect(res.messages[0].text).toBe('Edited register.tsx; tests next.')

  const ui = await $.ui.mount({ ...PANE, surface: 'desktop' })
  expect((await ui.find({ type: 'Text', text: /check ok/ }))).toBeTruthy()
  expect((await ui.find({ type: 'Text', text: /Open failures/ }))).toBeUndefined()
  await ui.unmount()
})

test('if the engine refuses the trimmed transcript, it compacts untrimmed', async ($, on) => {
  const seen: { compact?: any } = {}
  engine(on, seen, { summary: 's', refuseTrim: true })
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
  const res: any = await $.session.compact({ trigger: 'manual', messages: TRANSCRIPT } as any)
  expect(res.skip).toBeUndefined()
  expect(seen.compact.messages.every((m: any) => m.handle)).toBe(true)
})

test('/coach compact queues the compaction and retries if a turn still holds it', async ($, on) => {
  const seen: { compact?: any } = {}
  let attempts = 0
  const toasts: string[] = []
  on('command.register', () => ({ value: { command: 'coach' } }))
  on('ui.open', () => ({ value: { isPlaced: true } }))
  on('session.start', (_: any, e: any) => ({ cwd: e.cwd }))
  on('session.id', () => ({ value: 's1' }))
  on('session.usage', () => ({ value: { startedAt: 0, context: { window: 1000000 }, rateLimits: [] } }))
  on('fs.read', () => ({ value: '{}' }))
  on('fs.list', () => ({ value: [] }))
  on('fs.write', () => ({ value: undefined }))
  on('ui.toast', (_: any, e: any) => { toasts.push(e.text); return { value: undefined } })
  on('ui.status', () => ({ value: undefined }))
  on('ui.log', () => ({ value: undefined }))
  on('clock.now', () => ({ value: 1000 }))
  on('clock.after', () => ({ value: undefined }))  // the timer fires at once
  // The engine's /compact: refused once (a turn still held), then accepted. That
  // compaction reaching coach-watcher's own hook is what the tests above cover.
  on('command.run', async ($: any, e: any) => {
    if (e.command !== 'compact') return { text: 'engine' }
    attempts++
    if (attempts === 1) throw new Error('inside a hook the turn waits on')
    seen.compact = e
    return { text: 'Compacted' }
  })
  on('session.compact', (_: any, e: any) => {
    seen.compact = e
    return { messages: [{ role: 'user', text: 'summary', toolUses: [] }] }
  })
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })

  const out: any = await $.command.run({ command: 'coach', args: 'compact' } as any)
  expect(out.text).toContain('queued')
  for (let i = 0; i < 500 && !toasts.some(t => t.includes('Compacted')); i++) await Promise.resolve()
  expect(attempts).toBe(2)
  expect(seen.compact.command).toBe('compact')
  expect(toasts.some(t => t.includes("Compacted with Coach's notes"))).toBe(true)
})
