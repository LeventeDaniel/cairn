import { expect, test } from 'claude-code/testing'
import { advice, health, needsAndRunning, sessionHref, waitingHint } from './panel'
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

test('a waiting task shows the worker\'s own last line once the note is older than its last turn', () => {
  const base = { id: 't1', repo: 'r', title: 'r: job', kind: 'k', model: 'm', effort: 'e', session: 'local_j', status: 'waiting' as const, started: 0, updated: 0 }
  expect(waitingHint({ ...base, report: 'needs your OK to push' }, 0)).toBe('needs your OK to push')
  expect(waitingHint({ ...base, report: 'still running', reportStale: true, last: 'All tests pass, pushed.' }, 0)).toBe('Finished its turn: All tests pass, pushed.')
  expect(waitingHint({ ...base, report: 'still running', reportStale: true }, 0)).toBe('Finished its turn: open it and check')
  expect(waitingHint({ ...base, report: '', last: 'Started the run.', pending: 1, turnEnded: 60 }, 2760)).toBe('Quiet for 45 min with background work pending: check it')
})

test('a worker with a prompt open says so and is listed first', () => {
  const mk = (id: string, t: string, extra: object) => ({ id, repo: 'r', title: t, kind: 'k', model: 'm', effort: 'e', session: 'local_' + id, status: 'waiting' as const, started: 0, updated: 0, report: '', ...extra })
  const board = [mk('t1', 'r: finished', { last: 'All done.' }), mk('t2', 'r: stuck', { waitingFor: 'permission prompt', report: 'old note' })]
  const r = needsAndRunning(ws({ board, repos: [] }), ['billing'])
  expect(r.needs.map(n => n.text)).toEqual(['r: stuck', 'r: finished', 'Notes waiting for billing'])
  expect(r.needs[0]!.hint).toBe('Waiting for you: permission prompt')
  expect(r.needs[1]!.hint).toBe('Finished its turn: All done.')
})

test('a worker cut off by the usage limit says so instead of looking finished', () => {
  const base = { id: 't1', repo: 'r', title: 'r: job', kind: 'k', model: 'm', effort: 'e', session: 'local_j', status: 'waiting' as const, started: 0, updated: 0, report: 'still running', reportStale: true, last: 'API Error: Rate limit reached' }
  expect(waitingHint({ ...base, stopped: 'rate_limit' }, 0)).toBe('Cut off by the usage limit: tell it to continue after the reset')
  expect(waitingHint({ ...base, stopped: 'overloaded' }, 0)).toBe('Stopped by an error (overloaded): open it or tell it to continue')
})
