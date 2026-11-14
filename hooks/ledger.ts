/**
 * Savings ledger: what Cairn's compactions and cache warnings did, kept in
 * ~/.claude/cairn/state/ledger.json. Everything derived from it is an ESTIMATE:
 * the file records measured token counts, the savings are modelled from them.
 */
export type LedgerEvent =
  | { kind: 'compaction'; t: number; sid: string; by: 'cairn' | 'app'; before?: number; after?: number; cold?: boolean }
  | { kind: 'cache-warning'; t: number; sid: string; source: 'cold' | 'guard'; tokens: number }

export type LedgerCfg = {
  /** replies assumed to follow a compaction, each re-reading the saved tokens */
  ledger_turns: number
  /** USD per million tokens, cache read (the normal cost of re-reading context each reply) */
  ledger_read_usd_per_mtok: number
  /** USD per million tokens when the cache is cold (cache write, the full-price re-read) */
  ledger_write_usd_per_mtok: number
}

export const LEDGER_DEFAULTS: LedgerCfg = {
  ledger_turns: 10,
  ledger_read_usd_per_mtok: 0.3,
  ledger_write_usd_per_mtok: 3.75,
}

export const FILE = 'cairn/state/ledger.json'
const MAX_EVENTS = 500
/** A compaction within this long after a warning, same session, counts as "compacted after it". */
const FOLLOW_MS = 15 * 60000

export function addEvent(prev: readonly LedgerEvent[], ev: LedgerEvent): LedgerEvent[] {
  return [...prev, ev].slice(-MAX_EVENTS)
}

/** Keeps only well-formed events, so a damaged file never breaks the pane. */
export function parseLedger(raw: string): LedgerEvent[] {
  try {
    const v = JSON.parse(raw) as unknown
    if (!Array.isArray(v)) return []
    return v.filter((e): e is LedgerEvent =>
      !!e && typeof e === 'object' && typeof (e as LedgerEvent).t === 'number' &&
      ((e as LedgerEvent).kind === 'compaction' || (e as LedgerEvent).kind === 'cache-warning'))
  } catch {
    return []
  }
}

export type Summary = {
  compactions: number
  byCairn: number
  byApp: number
  tokensRemoved: number       // measured: before - after, summed
  tokensSaved: number         // estimate: removed x assumed later replies
  usdSaved: number            // estimate: of the above, at the cache-read price
  coldAvoided: number         // compactions Cairn ran for a cold or soon-cold cache
  coldUsd: number             // estimate: the one full-price re-read of the removed tokens
  warnings: number
  warningsFollowed: number
}

export function summarize(events: readonly LedgerEvent[], now: number, c: LedgerCfg = LEDGER_DEFAULTS, days = 7): Summary {
  const from = now - days * 86400000
  const inRange = events.filter(e => e.t >= from)
  const s: Summary = {
    compactions: 0, byCairn: 0, byApp: 0, tokensRemoved: 0, tokensSaved: 0, usdSaved: 0,
    coldAvoided: 0, coldUsd: 0, warnings: 0, warningsFollowed: 0,
  }
  const comps = inRange.filter((e): e is Extract<LedgerEvent, { kind: 'compaction' }> => e.kind === 'compaction')
  for (const e of comps) {
    s.compactions++
    if (e.by === 'cairn') s.byCairn++
    else s.byApp++
    const removed = Math.max(0, (e.before ?? 0) - (e.after ?? 0))
    s.tokensRemoved += removed
    // Only compactions Cairn chose count as savings: the app would have compacted anyway.
    if (e.by === 'cairn') {
      s.tokensSaved += removed * c.ledger_turns
      s.usdSaved += (removed * c.ledger_turns * c.ledger_read_usd_per_mtok) / 1e6
      if (e.cold) {
        s.coldAvoided++
        s.coldUsd += (removed * c.ledger_write_usd_per_mtok) / 1e6
      }
    }
  }
  for (const w of inRange) {
    if (w.kind !== 'cache-warning') continue
    s.warnings++
    if (comps.some(e => e.sid === w.sid && e.t >= w.t && e.t - w.t <= FOLLOW_MS)) s.warningsFollowed++
  }
  s.usdSaved += s.coldUsd
  return s
}

export type Days = Record<string, { usd: Record<string, number> }>

export type Compare =
  | { ok: true; since: string; before: number; after: number; nBefore: number; nAfter: number }
  | { ok: false; why: string }

/**
 * Average cost per session on days before the ledger's first event against days since.
 * Cairn can't prove cause (task mix differs), so it needs data on both sides.
 */
export function compareCost(events: readonly LedgerEvent[], days: Days, minSessions = 3): Compare {
  if (events.length === 0) return { ok: false, why: 'no Cairn events yet' }
  const first = events.reduce((a, e) => Math.min(a, e.t), Infinity)
  const since = new Date(first).toISOString().slice(0, 10)
  const keys = Object.keys(days).sort()
  const stat = (ks: string[]) => {
    const per = ks.flatMap(k => Object.values(days[k]!.usd))
    return { n: per.length, avg: per.length ? per.reduce((a, b) => a + b, 0) / per.length : 0 }
  }
  const b = stat(keys.filter(k => k < since)), a = stat(keys.filter(k => k >= since))
  if (b.n < minSessions) {
    return { ok: false, why: `no baseline: cost log has ${b.n} session(s) before ${since} (needs ${minSessions})${keys[0] ? `, it starts ${keys[0]}` : ''}` }
  }
  if (a.n < minSessions) return { ok: false, why: `only ${a.n} session(s) since ${since} (needs ${minSessions})` }
  return { ok: true, since, before: b.avg, after: a.avg, nBefore: b.n, nAfter: a.n }
}

const k = (n: number) => (n >= 1e6 ? (n / 1e6).toFixed(1) + 'M' : Math.round(n / 1000) + 'k')

/** Pane lines for the summary, plain strings so tests can match them. */
export function summaryLines(events: readonly LedgerEvent[], days: Days, now: number, c: LedgerCfg = LEDGER_DEFAULTS): string[] {
  const s = summarize(events, now, c)
  const out: string[] = []
  if (s.compactions === 0 && s.warnings === 0) out.push('Last 7 days: no compactions or cache warnings recorded yet.')
  else {
    out.push(`Last 7 days: ${s.compactions} compaction(s) (${s.byCairn} Cairn, ${s.byApp} app) · ${k(s.tokensRemoved)} tokens removed`)
    out.push(`Est. saved: ~${k(s.tokensSaved)} tokens, ~$${s.usdSaved.toFixed(2)}` +
      (s.coldAvoided ? ` (incl. ${s.coldAvoided} cold-cache re-read(s) avoided)` : ''))
    if (s.warnings) out.push(`Cache warnings: ${s.warnings}, compacted after ${s.warningsFollowed}`)
  }
  const cmp = compareCost(events, days)
  out.push(cmp.ok
    ? `Cost/session: $${cmp.before.toFixed(2)} before (${cmp.nBefore}) → $${cmp.after.toFixed(2)} since ${cmp.since} (${cmp.nAfter}); task mix differs, not proof.`
    : `Cost/session before vs after: not enough data (${cmp.why}).`)
  out.push(`Estimate only: ${c.ledger_turns} later replies per compaction at $${c.ledger_read_usd_per_mtok}/Mtok; cold re-read at $${c.ledger_write_usd_per_mtok}/Mtok.`)
  return out
}

/**
 * MEASURED numbers: bench/mine.py (history) and bench/run.py (A/B runs) write
 * ~/.claude/cairn/state/measured.json. Shown apart from the estimates above.
 */
export const MEASURED_FILE = 'cairn/state/measured.json'

export type Arm = { usd: number; turns: number; ctxAvg: number; cacheRead: number; cacheWrite: number; out: number }
export type Measured = {
  generated?: string
  history?: { compactions: number; medianBefore: number; medianAfter: number; minRepliesAfter: number; medianRepliesAfter: number; floor: number }
  bench?: { runs: number; model: string; off: Arm; on: Arm }
}

export function parseMeasured(raw: string): Measured | null {
  try {
    const v = JSON.parse(raw) as unknown
    return v && typeof v === 'object' ? (v as Measured) : null
  } catch {
    return null
  }
}

export function measuredLines(m: Measured | null): string[] {
  if (!m || (!m.history && !m.bench)) return ['Measured: nothing yet (run bench/mine.py, and bench/run.py once the CLI is logged in).']
  const out: string[] = []
  const h = m.history
  if (h) {
    out.push(`Measured (history, ${h.compactions} compactions): context ${k(h.medianBefore)} → ${k(h.medianAfter)}; ${h.minRepliesAfter}+ replies followed each (median ${h.medianRepliesAfter}).`)
    out.push(`Measured: every session starts at ~${k(h.floor)} tokens before Cairn adds anything.`)
  }
  const b = m.bench
  if (b) {
    const p = b.off.usd ? ((b.on.usd - b.off.usd) / b.off.usd) * 100 : 0
    out.push(`Measured A/B (${b.runs} runs/arm, ${b.model}): Cairn off $${b.off.usd.toFixed(3)}/run, on $${b.on.usd.toFixed(3)}/run (${p >= 0 ? '+' : ''}${p.toFixed(0)}%). Small sample.`)
  } else out.push('Measured A/B: not run yet, so no measured saving or cost for Cairn.')
  return out
}
