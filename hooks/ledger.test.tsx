import { expect, test } from 'claude-code/testing'
import { addEvent, compareCost, measuredLines, parseMeasured, summarize, summaryLines } from './ledger'
import type { LedgerEvent } from './ledger'

const norm = (p: unknown) => String(p).split(String.fromCharCode(92)).join('/')
const DAY = 86400000
const NOW = Date.UTC(2026, 10, 14, 12)

const comp = (daysAgo: number, by: 'cairn' | 'app', before: number, after: number, cold = false, sid = 's1'): LedgerEvent =>
  ({ kind: 'compaction', t: NOW - daysAgo * DAY, sid, by, before, after, ...(cold ? { cold: true } : {}) })

test('only Cairn-triggered compactions count as savings; the 7-day window applies', () => {
  const s = summarize([
    comp(1, 'cairn', 500000, 50000),
    comp(2, 'app', 400000, 40000),
    comp(9, 'cairn', 900000, 90000), // outside the window
  ], NOW)
  expect(s.compactions).toBe(2)
  expect(s.byCairn).toBe(1)
  expect(s.byApp).toBe(1)
  expect(s.tokensRemoved).toBe(450000 + 360000)
  expect(s.tokensSaved).toBe(450000 * 10)
  expect(Math.abs(s.usdSaved - 1.35) < 1e-9).toBe(true)
})

test('a cold-cache compaction adds the avoided full-price re-read; warnings track follow-up', () => {
  const warn = (daysAgo: number, sid: string): LedgerEvent =>
    ({ kind: 'cache-warning', t: NOW - daysAgo * DAY - 1000, sid, source: 'cold', tokens: 300000 })
  const s = summarize([warn(1, 's1'), comp(1, 'cairn', 300000, 30000, true), warn(2, 's2')], NOW)
  expect(s.coldAvoided).toBe(1)
  expect(Math.abs(s.coldUsd - 1.0125) < 1e-9).toBe(true)
  expect(s.warnings).toBe(2)
  expect(s.warningsFollowed).toBe(1)
})

test('cost comparison refuses to invent a baseline', () => {
  const days = { '2026-11-14': { usd: { a: 1, b: 2, c: 3 } } }
  const evs = [comp(0, 'cairn', 1, 0)]
  const c = compareCost(evs, days)
  expect(c.ok).toBe(false)
  expect(summaryLines(evs, days, NOW).join('\n')).toContain('not enough data')
  expect(compareCost([], days).ok).toBe(false)
})

test('cost comparison works with sessions on both sides', () => {
  const days = {
    '2026-11-10': { usd: { a: 4, b: 6, c: 5 } },
    '2026-11-13': { usd: { d: 2, e: 3, f: 1 } },
  }
  const c = compareCost([{ kind: 'compaction', t: Date.UTC(2026, 10, 12), sid: 'x', by: 'cairn' }], days)
  expect(c.ok).toBe(true)
  if (c.ok) { expect(c.before).toBe(5); expect(c.after).toBe(2) }
})

test('the ledger keeps at most 500 events', () => {
  let l: LedgerEvent[] = []
  for (let i = 0; i < 520; i++) l = addEvent(l, comp(0, 'app', i, 0))
  expect(l.length).toBe(500)
})

test('a compaction the app runs is logged as app; one Cairn queues is logged as cairn; the pane shows no estimate', async ($, on) => {
  const files: Record<string, string> = {}
  let running = () => {}
  let release = () => {}
  const started = new Promise<void>(r => { running = r })
  const gate = new Promise<void>(r => { release = r })
  const M = [{ role: 'user', text: 'hi', toolUses: [] }]
  on('command.register', () => ({ value: { command: 'cairn' } }))
  on('ui.open', () => ({ value: { isPlaced: true } }))
  on('session.start', (_: any, e: any) => ({ cwd: e.cwd }))
  on('session.id', () => ({ value: 's1' }))
  on('session.usage', () => ({ value: { startedAt: 0, context: { window: 1000000 }, rateLimits: [] } }))
  on('fs.read', (_: any, e: any) => ({ value: files[norm(e.path)] ?? '{}' }))
  on('fs.list', () => ({ value: [] }))
  on('fs.write', (_: any, e: any) => { files[norm(e.path)] = e.content ?? e.text ?? e.data; return { value: undefined } })
  on('ui.toast', () => ({ value: undefined }))
  on('ui.status', () => ({ value: undefined }))
  on('ui.log', () => ({ value: undefined }))
  on('clock.now', () => ({ value: NOW }))
  on('clock.after', () => ({ value: undefined }))
  on('command.run', async ($2: any, e: any) => {
    if (e.command === 'compact') { running(); await gate }
    return { text: 'ok' }
  })
  on('session.compact', () => ({ messages: [{ role: 'user', text: 's', toolUses: [] }], tokensBefore: 200000, tokensAfter: 20000 }))
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })

  await $.session.compact({ trigger: 'auto', messages: M } as any)
  await $.command.run({ command: 'cairn', args: 'compact' } as any)
  await started // Cairn's own queued /compact is running: a compaction now is Cairn's
  await $.session.compact({ trigger: 'manual', messages: M } as any)
  release()
  for (let i = 0; i < 800; i++) await Promise.resolve()

  const key = Object.keys(files).find(k => k.endsWith('cairn/state/ledger.json'))!
  const evs = JSON.parse(files[key]!) as LedgerEvent[]
  expect(evs.map(e => (e as any).by)).toEqual(['app', 'cairn'])

  const ui = await $.ui.mount({
    plugin: 'cairn', component: 'Pane', requestId: 'cairn', surface: 'desktop',
    props: { title: 'Cairn', isFocused: false, bodyColumns: 80, placement: 'dock', scroll: { offset: 0, bodyRows: 60 }, view: {} },
  } as any)
  await ui.press({ key: 'details' })
  // No modelled savings in the pane: what it shows is counted by `cairn.py stats`, or it says there is nothing yet.
  expect(await ui.find({ type: 'Text', text: /Est\. saved|Estimate only|saved about \$/ })).toBeUndefined()
  expect(await ui.find({ type: 'Text', text: /Not counted yet/ })).toBeTruthy()
  await ui.unmount()
})

test('measured lines are labelled and never invent an A/B result', () => {
  expect(measuredLines(null)[0]).toContain('nothing yet')
  const h = { compactions: 11, medianBefore: 245000, medianAfter: 98000, minRepliesAfter: 15, medianRepliesAfter: 433, floor: 80000 }
  const l = measuredLines({ history: h })
  expect(l[0]).toContain('Measured (history, 11 compactions)')
  expect(l.join(' ')).toContain('not run yet')
  const arm = { usd: 0.1, turns: 4, ctxAvg: 90000, cacheRead: 1, cacheWrite: 1, out: 1 }
  const ab = measuredLines({ bench: { runs: 3, model: 'haiku', off: arm, on: { ...arm, usd: 0.11 } } })
  expect(ab.join(' ')).toContain('+10%')
  expect(ab.join(' ')).toContain('Small sample')
  expect(parseMeasured('nope')).toBe(null)
})

test('a compaction after the cache already expired is not booked as a cold re-read avoided', async ($, on) => {
  // With the cache gone the summarizing request itself reads the history uncached; only the guard, which
  // compacts while the cache is still warm, avoids that read.
  const files: Record<string, string> = {}
  let running = () => {}
  let release = () => {}
  const started = new Promise<void>(r => { running = r })
  const gate = new Promise<void>(r => { release = r })
  on('command.register', () => ({ value: { command: 'cairn' } }))
  on('ui.open', () => ({ value: { isPlaced: true } }))
  on('session.start', (_: any, e: any) => ({ cwd: e.cwd }))
  on('session.id', () => ({ value: 's1' }))
  on('session.usage', () => ({ value: { startedAt: 0, context: { tokens: 200000, window: 1000000, percent: 20 }, rateLimits: [] } }))
  on('store.get', () => ({ value: { s1: { at: NOW - 3 * 3600000, tokens: 200000 } } }))
  on('store.set', () => ({ value: undefined }))
  on('fs.read', (_: any, e: any) => ({ value: files[norm(e.path)] ?? '{}' }))
  on('fs.list', () => ({ value: [] }))
  on('fs.write', (_: any, e: any) => { files[norm(e.path)] = e.content ?? e.text ?? e.data; return { value: undefined } })
  on('ui.toast', () => ({ value: undefined }))
  on('ui.status', () => ({ value: undefined }))
  on('ui.log', () => ({ value: undefined }))
  on('clock.now', () => ({ value: NOW }))
  on('clock.after', () => ({ value: undefined }))
  on('command.run', async ($2: any, e: any) => {
    if (e.command === 'compact') { running(); await gate }
    return { text: 'ok' }
  })
  on('session.compact', () => ({ messages: [{ role: 'user', text: 's', toolUses: [] }], tokensBefore: 200000, tokensAfter: 20000 }))
  await $.session.start({ cwd: '/', surface: 'desktop', isInteractive: true })
  await $.command.run({ command: 'cairn', args: 'compact' } as any)   // the person accepts the cold-start offer
  await started // that compaction is running
  await $.session.compact({ trigger: 'manual', messages: [{ role: 'user', text: 'hi', toolUses: [] }] } as any)
  release()
  for (let i = 0; i < 800; i++) await Promise.resolve()
  const key = Object.keys(files).find(k => k.endsWith('cairn/state/ledger.json'))!
  const comps = (JSON.parse(files[key]!) as LedgerEvent[]).filter(e => e.kind === 'compaction')
  expect(comps.map(e => (e as any).by)).toEqual(['cairn'])
  expect((comps[0] as any).cold).toBeUndefined()
})

test('with the floor known, only what went below it counts as removed', () => {
  const now = 10 * 86400000
  const ev = (floor?: number) => [{ kind: 'compaction' as const, t: now - 1000, sid: 's', by: 'cairn' as const,
    before: 95000, after: 16000, ...(floor ? { floor } : {}) }]
  expect(summarize(ev(), now).tokensRemoved).toBe(79000)        // the engine's count: summary alone
  expect(summarize(ev(85000), now).tokensRemoved).toBe(10000)   // what the next reply really ran at
  expect(summarize(ev(99000), now).tokensRemoved).toBe(0)
  // events from before a floor was learned are held against the one known now
  expect(summarize(ev(), now, { ledger_turns: 10, ledger_read_usd_per_mtok: 0.3, ledger_write_usd_per_mtok: 3.75, ledger_floor: 85000 }).tokensRemoved).toBe(10000)
})
