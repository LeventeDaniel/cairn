import { expect, test } from 'claude-code/testing'
import { advice, health, needsAndRunning, sessionHref } from './panel'
import type { Snap, Workspace } from '../types'

const ws = (over: Partial<Workspace> = {}): Workspace => ({
  at: 0, cacheTtlMin: 60, unregistered: [],
  repos: [{ name: 'r', path: '/r', purpose: '', goal: '', next: '', notes: 0, worktrees: 0, sessions: [
    { id: 'local_aaa', title: 'r: build x', status: 'busy', ageMin: 1, warm: true },
    { id: 'local_bbb', title: 'r: ask y', status: 'waiting', ageMin: 1, warm: true },
    { id: 'local_ccc', title: 'r: old', status: 'idle', ageMin: 99, warm: false },
  ] }],
  ...over,
})
const snap = (limits: Snap['limits'], level = 0): Snap => ({ window: 1, limits, level, inbox: [], at: 0 })

test('needs you and running are plain lists, idle sessions are left out', () => {
  const r = needsAndRunning(ws(), [])
  expect(r.needs.map(n => n.text)).toEqual(['r: ask y'])
  expect(r.needs[0]!.href).toBe('#local_bbb')
  expect(r.running.map(n => n.text)).toEqual(['r: build x'])
  expect(needsAndRunning(null, []).needs).toEqual([])
})

test('a board task and its live session show once', () => {
  const board = [{ id: 't1', repo: 'r', title: 'r: ask y', kind: 'k', model: 'm', effort: 'e', session: 'local_bbb', status: 'waiting' as const, started: 0, updated: 0, report: 'confirm the cap' }]
  const r = needsAndRunning(ws({ board }), ['billing'])
  expect(r.needs.map(n => n.text)).toEqual(['r: ask y', 'Notes waiting for billing'])
  expect(r.needs[0]!.hint).toBe('confirm the cap')
})

test('savings show only with real ledger data; advice only when action is needed', () => {
  expect(health(snap([]), [], 0, 80).saved).toBeUndefined()
  const ev = [{ kind: 'compaction' as const, t: 1000, sid: 's', by: 'cairn' as const, before: 200000, after: 20000 }]
  expect(health(snap([]), ev, 2000, 80).saved).toMatch(/^Cairn saved about \$\d+(\.\d\d)? this week \(estimate\)$/)
  expect(advice(health(snap([{ kind: 'five_hour', percentUsed: 20 }]), [], 0, 80), snap([]))).toBeUndefined()
  expect(advice(health(snap([{ kind: 'five_hour', percentUsed: 85 }]), [], 0, 80), snap([]))).toMatch(/high/)
  expect(sessionHref('nope')).toBeUndefined()
})
