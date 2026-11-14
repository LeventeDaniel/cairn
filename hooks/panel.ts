import type { BoardTask, Snap, Workspace } from '../types'
import { summarize } from './ledger'
import type { LedgerCfg, LedgerEvent } from './ledger'

/** One line of the default view. `href` opens that session when the app knows its id. */
export type Item = { text: string; hint?: string; href?: string }

export type Health = {
  /** 5-hour plan use, 0-100, undefined without a reading */
  fiveHour?: number
  sevenDay?: number
  /** 'ok' | 'high' (>= usage_warn) */
  level: 'ok' | 'high'
  /** "Cairn saved about $N this week (estimate)", only with real ledger data */
  saved?: string
}

const clip = (s: string, n: number) => {
  const t = s.replace(/\s+/g, ' ').trim()
  return t.length > n ? t.slice(0, n - 1) + '…' : t
}

/** Link target for a session id: the app's own `#local_<id>` form, else none. */
export const sessionHref = (id?: string | null): string | undefined =>
  id ? (id.startsWith('local_') ? `#${id}` : /^[0-9a-f-]{36}$/i.test(id) ? `#local_${id}` : undefined) : undefined

/** Titles like "cairn: simplify the pane UI" read better without the repo prefix noise; keep as is, just clip. */
const title = (t: string) => clip(t, 48)

/**
 * Why a board task waits. Home's note counts while it is newer than the worker's last turn; after
 * that the worker's own last line (written by its Stop hook) is the truth, not an old "still running".
 */
export function waitingHint(t: BoardTask, now: number): string {
  if (t.waitingFor) return `Waiting for you: ${t.waitingFor}`
  if (t.report && !t.reportStale) return clip(t.report, 70)
  if (t.pending && t.turnEnded) return `Quiet for ${Math.round((now - t.turnEnded) / 60)} min with background work pending: check it`
  return t.last ? clip(`Finished its turn: ${t.last}`, 90) : 'Finished its turn: open it and check'
}

/**
 * What needs the person, and what runs now, from Cairn Home's board and the live sessions of
 * every repo. A board task and a live session for the same thing show once.
 */
export function needsAndRunning(w: Workspace | null, inbox: readonly string[]): { needs: Item[]; running: Item[] } {
  const needs: Item[] = []
  const running: Item[] = []
  if (!w) return { needs: inbox.length ? [{ text: `Notes waiting for ${inbox.join(', ')}` }] : [], running }
  const seen = new Set<string>()
  for (const t of w.board ?? []) {
    const key = t.cliSession || t.session
    if (t.status === 'waiting') {
      needs.push({ text: title(t.title), hint: waitingHint(t, w.at), href: sessionHref(t.session) })
      seen.add(key); seen.add(t.title)
    } else if (t.status === 'running') {
      running.push({ text: title(t.title), href: sessionHref(t.session) })
      seen.add(key); seen.add(t.title)
    }
  }
  for (const r of w.repos) {
    for (const s of r.sessions) {
      if (seen.has(s.id) || seen.has(s.title)) continue
      if (s.status === 'waiting') needs.push({ text: title(s.title), hint: s.waitingFor ? `Waiting for you: ${s.waitingFor}` : 'Waiting for your answer', href: sessionHref(s.id) })
      else if (s.status === 'busy') running.push({ text: title(s.title), href: sessionHref(s.id) })
    }
  }
  // A worker with a prompt open comes first: it is stuck until answered; the rest only wait to be read.
  const open = new Set((w.board ?? []).filter(t => t.status === 'waiting' && t.waitingFor).map(t => title(t.title)))
  needs.sort((a, b) => Number(open.has(b.text)) - Number(open.has(a.text)))
  if (inbox.length) needs.push({ text: `Notes waiting for ${inbox.join(', ')}`, hint: 'They show up in your next session there' })
  return { needs, running }
}

/** Plan use plus a savings line that appears only when the ledger recorded real Cairn compactions. */
export function health(s: Snap, events: readonly LedgerEvent[], now: number, usageWarn: number, c?: LedgerCfg): Health {
  const lim = (kind: string) => s.limits.find(l => l.kind === kind)?.percentUsed
  const fh = lim('five_hour'), sd = lim('seven_day')
  const sum = summarize(events, now, c)
  const saved = sum.byCairn > 0 && sum.usdSaved >= 0.01
    ? `Cairn saved about $${sum.usdSaved < 10 ? sum.usdSaved.toFixed(2) : Math.round(sum.usdSaved)} this week (estimate)`
    : undefined
  return { fiveHour: fh, sevenDay: sd, level: (fh ?? 0) >= usageWarn || (sd ?? 0) >= usageWarn ? 'high' : 'ok', saved }
}

/** At most one short sentence, and only when the person should act. */
export function advice(h: Health, s: Snap): string | undefined {
  if ((h.fiveHour ?? 0) >= 95) return 'Your 5-hour limit is almost used: pause big jobs until it resets.'
  if (h.level === 'high') return 'Plan use is high: keep new work small.'
  if (s.level === 2) return 'This chat is getting very long: start a fresh one soon.'
  return undefined
}
