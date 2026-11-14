import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register, SessionMessage, SessionUsage } from 'claude-code'

import type { Compaction, Offer, Snap, Work, Workspace } from '../types'
import { LEDGER_DEFAULTS, FILE as LEDGER_FILE, MEASURED_FILE, addEvent, measuredLines, parseLedger, parseMeasured, summaryLines } from './ledger'
import type { LedgerEvent } from './ledger'
import { advice, health, needsAndRunning } from './panel'
import type { Item } from './panel'

const VERSION = '0.8.0'
const PANE = 'cairn'
const TITLE = 'Cairn'
// Tunable in ~/.claude/cairn/config.json, next to Cairn's own keys.
const DEFAULTS = {
  warn: 50, urgent: 70, usage_warn: 80,
  // smart: Cairn decides (clean breaks, idle time, hard limit); ask: offer only;
  // auto: compact at compact_at whatever the state; off: never
  compact_mode: 'smart' as 'smart' | 'ask' | 'auto' | 'off',
  compact_soft: 40,    // % from which a finished task is a reason to compact
  compact_at: 60,      // % from which any calm turn end is
  compact_hard: 72,    // % at which Cairn compacts at the next turn end, mid-task or not
  idle_minutes: 3,     // an offer nobody answered runs after this long with no new prompt
  trim_over: 4000,     // tool results longer than this (chars) are trimmed before summarizing
  trim_keep: 800,      // chars kept from a trimmed result (head + tail)
  // The prompt cache keeps a context cheap to re-read for this long after the last
  // reply (60 min on plans with the 1-hour cache, 5 in usage overage). Past it, the
  // next reply re-reads the whole context at full price.
  cache_ttl_minutes: 60,
  cache_min_tokens: 60000, // below this a cold re-read is cheap: leave the context alone
  // Cairn Home (a session in ~/.claude/cairn/home) holds only the board: compact it early and often.
  home_compact_soft: 15,
  home_compact_at: 25,
  home_compact_hard: 50,
  ...LEDGER_DEFAULTS,
}
type Cfg = typeof DEFAULTS

const snap = atom({ plugin: 'cairn', key: 'snap' } as const, {
  window: 0, limits: [], level: 0, inbox: [], at: 0,
} as Snap, { shape: 'snap-1' })
const work = atom({ plugin: 'cairn', key: 'work' } as const,
  { files: [], fails: [], oks: [] } as Work, { shape: 'work-1' })
const comps = atom({ plugin: 'cairn', key: 'comps' } as const,
  [] as Compaction[], { shape: 'comps-1' })
const offer = atom({ plugin: 'cairn', key: 'offer' } as const,
  null as Offer | null, { shape: 'offer-1' })
/** Per day: cost by session (so several sessions add up) and the highest plan-usage readings. */
export type Days = Record<string, { usd: Record<string, number>; fh?: number; sd?: number }>
const days = atom({ plugin: 'cairn', key: 'days' } as const, {} as Days, { shape: 'days-1' })
/** Savings ledger events (~/.claude/cairn/state/ledger.json); see ledger.ts. */
const ledger = atom({ plugin: 'cairn', key: 'ledger' } as const, [] as LedgerEvent[], { shape: 'ledger-1' })
/** Pane lines for measured (not estimated) numbers; see ledger.ts. */
const measured = atom({ plugin: 'cairn', key: 'measured' } as const, [] as string[], { shape: 'measured-1' })
/** Whether the pane's Details section is open (off by default). */
const details = atom({ plugin: 'cairn', key: 'details' } as const, false, { shape: 'details-1' })
const ws = atom({ plugin: 'cairn', key: 'ws' } as const,
  null as Workspace | null, { shape: 'ws-1' })

/** ~/.claude, taken from where the mod lives (…/.claude/dev-mods/… or …/.claude/plugins/…). */
function claudeDir(root: string): string {
  const p = root.replace(/\\/g, '/')
  const i = p.toLowerCase().lastIndexOf('/.claude/')
  return i >= 0 ? p.slice(0, i + '/.claude'.length) : p
}

/** Same rule as cairn.py's safe_id, so both name the same state file. */
const safeId = (s: string) => s.replace(/[^A-Za-z0-9_-]/g, '').slice(0, 80) || 'unknown'

const pct = (limits: Snap['limits'], kind: string) =>
  limits.find(l => l.kind === kind)?.percentUsed

const oneLine = (s: string, n: number) => s.replace(/\s+/g, ' ').trim().slice(0, n)
const baseName = (p: string) => p.replace(/\\/g, '/').split('/').pop() || p

let lastLevel = 0
let cfg: Cfg = { ...DEFAULTS }
let compacting = false
// This main-loop turn's signs that a piece of work just finished.
let turnDone = ''      // what finished, '' if nothing
let turnSeq = 0        // main-loop turns started; an idle timer checks nothing new began
let snoozedTo = 0      // "Not now": no new offer below this %
let cairnRun = false   // a compaction Cairn queued is running (the app's own are not)
let coldRun = false    // ...and it was for a cold or soon-cold prompt cache
let compactions = 0    // main-loop compactions done; a cache timer checks none ran since

/** True when this session runs in Cairn Home's folder (~/.claude/cairn/home). */
async function inHome($: EngineInterface, home: string): Promise<boolean> {
  try {
    const norm = (x: string) => x.replace(/\\/g, '/').replace(/\/+$/, '').toLowerCase()
    const cwd = norm(await $.session.cwd())
    return cwd === norm(`${home}/cairn/home`) || cwd.endsWith('/.claude/cairn/home')
  } catch {
    return false
  }
}

async function loadCfg($: EngineInterface, home: string) {
  // The engine's own cache TTL setting, unless config.json names one.
  let ttl: Partial<Cfg> = {}
  try {
    const v = await $.settings.read({ key: 'promptCacheTtl' })
    if (v === '5m') ttl = { cache_ttl_minutes: 5 }
    else if (v === '1h') ttl = { cache_ttl_minutes: 60 }
  } catch { /* settings unreadable: keep the default */ }
  try {
    cfg = { ...DEFAULTS, ...ttl, ...JSON.parse(await $.fs.read(`${home}/cairn/config.json`)) }
  } catch {
    cfg = { ...DEFAULTS, ...ttl }
  }
  if (await inHome($, home)) {
    cfg = { ...cfg, compact_soft: cfg.home_compact_soft, compact_at: cfg.home_compact_at, compact_hard: cfg.home_compact_hard }
  }
}

// ------------------------------------------------------------ workspace (9)
let wsAt = 0
let wsBusy = false

/** Python and cairn.py (coach.py before the rename), read off the UserPromptSubmit hook that runs Cairn. */
async function cairnCommand($: EngineInterface): Promise<string[] | undefined> {
  const hooks = (await $.settings.read({ key: 'hooks' })) as Record<string, { hooks?: { command?: string }[] }[]> | undefined
  for (const group of hooks?.UserPromptSubmit ?? []) {
    for (const h of group.hooks ?? []) {
      const m = h.command?.match(/^\s*("[^"]+"|\S+)\s+("[^"]+"|\S+(?:cairn|coach)\.py)\b/)
      if (m) return [m[1]!.replace(/"/g, ''), m[2]!.replace(/"/g, '')]
    }
  }
  return undefined
}

/** Every registered repo's goal, sessions and notes, from `cairn.py workspace --json`; at most once a minute. */
async function refreshWorkspace($: EngineInterface, force = false) {
  const now = await $.clock.now()
  if (wsBusy || (!force && now - wsAt < 60000)) return
  wsBusy = true
  let changed = false
  wsAt = now
  try {
    const cmd = await cairnCommand($)
    if (!cmd) return
    const r = await $.process.run([...cmd, 'workspace', '--json'], { timeoutMs: 45000 })
    if (r.exitCode !== 0) throw new Error(r.stderr.slice(0, 300))
    const w = JSON.parse(r.stdout) as Workspace
    const key = JSON.stringify({ ...w, at: 0 })
    changed = key !== wsKey
    wsKey = key
    // Only Cairn Home speaks for the board; other open sessions stay quiet.
    const speak = await inHome($, claudeDir($.plugin.root))
    for (const t of speak ? w.board ?? [] : []) {
      const was = boardSeen.get(t.id)
      if (boardSeen.size > 0 && was !== undefined && was !== t.status && (t.status === 'done' || t.status === 'waiting')) {
        $.ui.toast((t.status === 'done' ? 'Finished: ' : 'Needs you: ') + t.title.slice(0, 50) + (t.report && !t.reportStale ? ' - ' + t.report.slice(0, 60) : ''))
      }
    }
    boardSeen = new Map((w.board ?? []).map(t => [t.id, t.status]))
    await update($, ws, () => w)
  } catch (err) {
    $.ui.log(`cairn: workspace refresh failed: ${String(err)}`)
  } finally {
    wsBusy = false
    if (changed || !timerFired) armWorkspaceTimer($)
    timerFired = false
  }
}

// An idle session gets no turn-end refresh, so the pane would go stale: re-read after 2 minutes, and keep
// going only while the board keeps changing (an unchanged re-read ends the chain).
let wsTimer = false
let wsKey = ''
let boardSeen = new Map<string, string>()
let timerFired = false
function armWorkspaceTimer($: EngineInterface) {
  if (wsTimer) return
  wsTimer = true
  $.clock.after(120000, () => {
    wsTimer = false
    timerFired = true
    void refreshWorkspace($, true)
  })
}

async function inbox($: EngineInterface, home: string): Promise<string[]> {
  try {
    const list = await $.fs.list(`${home}/inbox`)
    return list
      .filter(f => f.kind === 'file' && f.name.endsWith('.md') && f.size > 0)
      .map(f => f.name.replace(/\.md$/, ''))
  } catch {
    return []
  }
}

// ------------------------------------------------------------ work tracking (1)
async function record($: EngineInterface, tool: string, input: Record<string, unknown>,
  ran: { deny?: string; isError?: true; text?: string }) {
  if (ran.deny !== undefined) return
  const file = (input.file_path ?? input.notebook_path) as string | undefined
  const cmd = typeof input.command === 'string' ? oneLine(input.command, 160) : undefined
  const now = await $.clock.now()
  if (!ran.isError) {
    // A wrap-up that still asks the person something leaves work pending.
    if (/(^|__)wrap_up$/.test(tool)) { if (!input.ask) turnDone ||= 'task wrapped up' }
    else if (cmd && /\bgit\s+(commit|push)\b/.test(cmd)) turnDone = /push/.test(cmd) ? 'work pushed' : 'work committed'
    else if (cmd && (await read($, work)).fails.some(f => f.cmd === cmd)) turnDone ||= 'failing command passes now'
  }
  if ((tool === 'Edit' || tool === 'Write' || tool === 'NotebookEdit' || tool === 'MultiEdit') && file && !ran.isError) {
    await update($, work, w => ({ ...w, files: [...w.files.filter(f => f !== file), file].slice(-40) }))
  } else if ((tool === 'Bash' || tool === 'PowerShell') && cmd) {
    if (ran.isError) {
      const error = oneLine((ran.text ?? '').split('\n').filter(l => l.trim()).slice(-3).join(' | '), 300)
      await update($, work, w => ({ ...w, fails: [...w.fails.filter(f => f.cmd !== cmd), { cmd, error, at: now }].slice(-8) }))
    } else {
      await update($, work, w => ({
        ...w,
        fails: w.fails.filter(f => f.cmd !== cmd),
        oks: [...w.oks.filter(c => c !== cmd), cmd].slice(-6),
      }))
    }
  }
}

/** How many files were edited after SESSION.md was last written (all of them if it never was). */
function editsBehind(files: readonly string[]): number {
  const i = files.map(f => baseName(f).toUpperCase()).lastIndexOf('SESSION.MD')
  return files.length - (i + 1)
}

// ------------------------------------------------------------ instructions (2, 6)
async function sessionNotes($: EngineInterface): Promise<{ goal?: string; next?: string }> {
  try {
    const t = await $.fs.read('SESSION.md')
    const sec = (name: string) => t.match(new RegExp(`##\\s*${name}[^\\n]*\\n+([\\s\\S]*?)(?=\\n##|$)`, 'i'))?.[1]?.trim()
    return { goal: sec('Goal')?.slice(0, 300), next: sec('Next')?.slice(0, 600) }
  } catch {
    return {}
  }
}

function latestAsks(messages: readonly SessionMessage[]): string[] {
  return messages
    .filter(m => m.role === 'user' && m.text.trim() && !(m.toolResults?.length) &&
      !m.text.startsWith('<') && !m.text.startsWith('[Cairn'))
    .slice(-4)
    .map(m => oneLine(m.text, 300))
}

function stateBlock(w: Work, notes: { goal?: string; next?: string }, asks: string[]): string {
  const out: string[] = []
  out.push(`Goal: ${notes.goal ?? "not written down; infer it from the user's latest requests below"}`)
  if (notes.next) out.push(`Next steps (SESSION.md):\n${notes.next}`)
  if (w.files.length) out.push(`Files edited this session (most recent last): ${w.files.slice(-25).join(', ')}`)
  if (w.fails.length) out.push('Commands that failed and have not succeeded since:\n' +
    w.fails.map(f => `- \`${f.cmd}\` → ${f.error || 'error'}`).join('\n'))
  if (w.oks.length) out.push(`Recent commands that worked: ${w.oks.map(c => `\`${c}\``).join(', ')}`)
  if (asks.length) out.push("The user's latest requests (most recent last):\n" + asks.map((a, i) => `${i + 1}. ${a}`).join('\n'))
  return out.join('\n')
}

async function mainInstructions($: EngineInterface, messages: readonly SessionMessage[]): Promise<string> {
  const w = await read($, work)
  return '[Cairn] Keep these facts exactly in the summary, with exact paths and commands:\n' +
    stateBlock(w, await sessionNotes($), latestAsks(messages)) +
    '\nKeep: the goal, decisions and why, open errors, exact file paths, what is next. ' +
    'Drop: raw file contents, long logs, search dumps, attempts that were superseded.'
}

const SUBAGENT_INSTRUCTIONS = '[Cairn] This is a subagent transcript. Keep only: the task it was given, ' +
  'its findings with file:line references, conclusions, and anything still unresolved. Drop exploration, ' +
  'raw file contents and dead ends.'

// ------------------------------------------------------------ trimming (3)
function trimMessages(messages: readonly SessionMessage[], c: Cfg) {
  const label = new Map<string, string>()
  for (const m of messages) for (const u of m.toolUses) {
    const i = u.input
    const what = (i.file_path ?? i.notebook_path ?? i.command ?? i.pattern ?? i.url ?? i.query ?? '') as string
    label.set(u.tool_use_id, `${u.tool}${what ? ' ' + oneLine(String(what), 120) : ''}`)
  }
  let count = 0, chars = 0
  const out = messages.map(m => {
    const rs = m.toolResults
    if (m.role !== 'user' || !rs?.length) return m
    const limit = (isError: boolean) => (isError ? c.trim_over * 4 : c.trim_over)
    if (!rs.some(r => r.text.length > limit(r.isError))) return m
    const toolResults = rs.map(r => {
      if (r.text.length <= limit(r.isError)) return { tool_use_id: r.tool_use_id, text: r.text, isError: r.isError }
      const head = Math.floor(c.trim_keep * 0.75), tail = c.trim_keep - head
      const cut = r.text.length - head - tail
      count++; chars += cut
      return {
        tool_use_id: r.tool_use_id, isError: r.isError,
        text: r.text.slice(0, head) +
          `\n…[Cairn trimmed ${cut} chars of ${label.get(r.tool_use_id) ?? 'tool output'}; re-run it if needed]…\n` +
          r.text.slice(-tail),
      }
    })
    // No handle: the engine builds this copy from its role, text and tool blocks.
    return { role: m.role, text: m.text, toolUses: [], toolResults } as SessionMessage
  })
  return { messages: out, count, chars }
}

// ------------------------------------------------------------ summary check (4)
function checkSummary(messages: readonly SessionMessage[], w: Work, block: string) {
  const recent = w.files.slice(-5)
  if (!recent.length) return { messages, check: 'n/a' as const }
  const all = messages.map(m => m.text).join('\n').toLowerCase()
  const missing = recent.filter(f => !all.includes(baseName(f).toLowerCase()))
  if (!missing.length) return { messages, check: 'ok' as const }
  // Patch the summary itself (the first plain message) so no extra turn is added.
  const i = messages.findIndex(m => !m.toolUses.length && !(m.toolResults?.length))
  const note = '\n\n[Cairn] State carried across this compaction:\n' + block
  const patched = i >= 0
    ? messages.map((m, j) => (j === i ? { role: m.role, text: m.text + note, toolUses: [] } as SessionMessage : m))
    : [{ role: 'user', text: note.trim(), toolUses: [] } as SessionMessage, ...messages]
  return { messages: patched, check: 'patched' as const }
}

// ------------------------------------------------------------ usage per day
/** Adds one reading to the per-day log; keeps the last 14 days. Pure, so it can be tested. */
export function addUsage(prev: Days, day: string, sid: string, usd: number | undefined, fh?: number, sd?: number): Days {
  const d = prev[day] ?? { usd: {} }
  const next = {
    usd: usd === undefined ? d.usd : { ...d.usd, [sid]: Math.max(d.usd[sid] ?? 0, usd) },
    fh: fh === undefined ? d.fh : Math.max(d.fh ?? 0, fh),
    sd: sd === undefined ? d.sd : Math.max(d.sd ?? 0, sd),
  }
  const all = { ...prev, [day]: next }
  return Object.fromEntries(Object.keys(all).sort().slice(-14).map(k => [k, all[k]!]))
}

function dayLine(day: string, d: Days[string]): string {
  const usd = Object.values(d.usd).reduce((a, b) => a + b, 0).toFixed(2)
  return day.slice(5) + ' $' + usd + ' (' + Object.keys(d.usd).length + ' sessions) · peak 5h ' +
    (d.fh?.toFixed(0) ?? '–') + '% · 7d ' + (d.sd?.toFixed(0) ?? '–') + '%'
}

let daysAt = -Infinity
async function logUsage($: EngineInterface, home: string, usd: number | undefined, fh?: number, sd?: number) {
  const now = await $.clock.now()
  if (now - daysAt < 60000) return
  daysAt = now
  const file = `${home}/cairn/state/usage-days.json`
  let prev: Days = {}
  try {
    const raw = JSON.parse(await $.fs.read(file)) as Record<string, unknown>
    for (const [k, v] of Object.entries(raw)) {
      if (/^\d{4}-\d{2}-\d{2}$/.test(k) && v && typeof v === 'object' && typeof (v as Days[string]).usd === 'object') prev[k] = v as Days[string]
    }
  } catch { /* first reading */ }
  const day = new Date(now).toISOString().slice(0, 10)
  const sid = safeId(await $.session.id())
  const next = addUsage(prev, day, sid, usd, fh, sd)
  await $.fs.write(file, JSON.stringify(next))
  await update($, days, () => next)
}

// ------------------------------------------------------------ savings ledger
async function logEvent($: EngineInterface, ev: LedgerEvent) {
  try {
    const file = `${claudeDir($.plugin.root)}/${LEDGER_FILE}`
    let prev: LedgerEvent[] = []
    try { prev = parseLedger(await $.fs.read(file)) } catch { /* first event */ }
    const next = addEvent(prev, ev)
    await $.fs.write(file, JSON.stringify(next))
    await update($, ledger, () => next)
  } catch (err) {
    $.ui.log(`cairn: could not write the ledger: ${String(err)}`)
  }
}

async function warned($: EngineInterface, source: 'cold' | 'guard', tokens: number) {
  await logEvent($, { kind: 'cache-warning', t: await $.clock.now(), sid: safeId(await $.session.id()), source, tokens })
}

// ------------------------------------------------------------ measuring
async function refresh($: EngineInterface, u: Pick<SessionUsage, 'context' | 'rateLimits' | 'cost'>) {
  const home = claudeDir($.plugin.root)
  await loadCfg($, home)
  const p = u.context.percent
  const level = p === undefined ? 0 : p >= cfg.urgent ? 2 : p >= cfg.warn ? 1 : 0
  const s: Snap = {
    percent: p,
    tokens: u.context.tokens,
    window: u.context.window,
    limits: u.rateLimits.map(l => ({ kind: l.kind, percentUsed: l.percentUsed })),
    usd: u.cost?.usd,
    level,
    inbox: await inbox($, home),
    at: await $.clock.now(),
  }
  await update($, snap, () => s)

  const parts: string[] = []
  if (p !== undefined) parts.push(`${p.toFixed(0)}% ctx${level === 2 ? ' ⚠ clear soon' : level === 1 ? ' ●' : ''}`)
  const fh = pct(s.limits, 'five_hour'), sd = pct(s.limits, 'seven_day')
  if (fh !== undefined) parts.push(`5h ${fh.toFixed(0)}%`)
  if (sd !== undefined) parts.push(`7d ${sd.toFixed(0)}%`)
  $.ui.status(parts.length ? 'Cairn · ' + parts.join(' · ') : undefined)

  // With compaction on, Cairn's own decisions speak for it (decide(), the band).
  if (level > lastLevel && cfg.compact_mode === 'off') {
    $.ui.toast(level === 2
      ? `Context ${p!.toFixed(0)}% full: save with handoff, then /clear`
      : `Context ${p!.toFixed(0)}% full: plan a handoff at the next stopping point`)
  }
  lastLevel = level

  try {
    await logUsage($, home, s.usd, fh, sd)
  } catch (err) {
    $.ui.log(`cairn: could not log usage: ${String(err)}`)
  }

  const state = {
    t: Date.now() / 1000, pct: p ?? null, window: s.window || null,
    five_hour: fh ?? null, seven_day: sd ?? null, model: null, via: 'cairn',
  }
  try {
    const sid = safeId(await $.session.id())
    const text = JSON.stringify(state)
    await $.fs.write(`${home}/cairn/state/${sid}.json`, text)
    await $.fs.write(`${home}/cairn/state/last.json`, text)
  } catch (err) {
    $.ui.log(`cairn: could not write state: ${String(err)}`)
  }
  return p
}

// ------------------------------------------------------------ when to compact (5)
/**
 * Called at each main-loop turn end. Picks one of: compact now, offer (band
 * above the prompt, and compact if the person stays away idle_minutes), or wait.
 *
 * - at compact_hard: now, so the engine's own auto-compact never cuts in mid-task
 * - an open failure below compact_hard: wait, the debugging context is still needed
 *   (finished work clears open failures first, see decide())
 * - from compact_at: a finished piece of work → now; any other calm end → offer
 * - from compact_soft: a finished piece of work → offer
 */
function verdict(p: number, mode: Cfg['compact_mode'], c: Cfg, done: string, openFails: number,
  snoozed: number): { act: 'now' | 'offer' | 'wait'; reason: string } {
  const wait = { act: 'wait' as const, reason: '' }
  if (mode === 'off' || p < c.compact_soft) return wait
  if (mode === 'auto') return p >= c.compact_at ? { act: 'now', reason: `context past ${c.compact_at}%` } : wait
  if (p >= c.compact_hard) {
    return mode === 'ask' ? { act: 'offer', reason: `context ${p.toFixed(0)}%, near the limit` }
      : { act: 'now', reason: `context ${p.toFixed(0)}%, before auto-compact cuts in mid-task` }
  }
  if (openFails > 0 || p < snoozed) return wait
  if (p >= c.compact_at) {
    if (done && mode === 'smart') return { act: 'now', reason: `${done}, context ${p.toFixed(0)}%` }
    return { act: 'offer', reason: done ? `${done}, context ${p.toFixed(0)}%` : `context ${p.toFixed(0)}%, a calm point` }
  }
  return done ? { act: 'offer', reason: `${done}, context ${p.toFixed(0)}%` } : wait
}

async function decide($: EngineInterface) {
  const done = turnDone
  turnDone = ''
  if (pending || compacting) return
  const p = (await read($, snap)).percent
  if (p === undefined) return
  // Finished work closes the failures left from earlier: a command that failed
  // once (a stray ls, a probe) must not hold back every later offer.
  if (done) await update($, work, x => ({ ...x, fails: [] }))
  const w = await read($, work)
  const v = verdict(p, cfg.compact_mode, cfg, done, w.fails.length, snoozedTo)
  try {
    // The last decision, for anyone checking why Cairn did or didn't compact.
    await $.fs.write(`${claudeDir($.plugin.root)}/cairn/state/compact-decision.json`, JSON.stringify({
      t: Date.now() / 1000, version: VERSION, pct: p, mode: cfg.compact_mode, done, openFails: w.fails.length,
      snoozedTo, act: v.act, reason: v.reason,
    }))
  } catch { /* the log is optional */ }
  if (v.act === 'wait') return
  if (v.act === 'now') {
    await update($, offer, () => null)
    $.ui.toast(`Cairn is compacting: ${v.reason}`)
    queueCompact($)
    return
  }
  const at = await $.clock.now()
  await update($, offer, () => ({ percent: p, reason: v.reason, at }))
  if (cfg.compact_mode === 'smart') {
    // Nobody answers and no turn starts: compact while the person is away.
    const seq = turnSeq
    $.clock.after(cfg.idle_minutes * 60000, () => { void idleCompact($, seq) })
  }
}

/**
 * A worker Cairn Home started whose board task is done or closed. Nobody is going to send it another
 * message, so compacting it while it sits idle buys nothing and spends plan usage (with many finished
 * workers open, a compaction each). The offer stays up for the person who does come back to it.
 */
async function finishedWorker($: EngineInterface): Promise<boolean> {
  try {
    const sid = await $.session.id()
    const b = JSON.parse(await $.fs.read(`${claudeDir($.plugin.root)}/cairn/board.json`)) as
      { tasks?: { cliSession?: string; status?: string }[] }
    const mine = (b.tasks ?? []).filter(t => t.cliSession === sid)
    return mine.length > 0 && mine.every(t => t.status === 'done' || t.status === 'closed')
  } catch {
    return false
  }
}

async function idleCompact($: EngineInterface, seq: number) {
  if (seq !== turnSeq || pending || compacting || !(await read($, offer))) return
  if (await finishedWorker($)) return
  await update($, offer, () => null)
  $.ui.toast("Cairn compacted while you were away: see the Cairn pane")
  queueCompact($)
}

// ------------------------------------------------------------ prompt cache (8)
const k = (n?: number) => (n === undefined ? '?' : `${Math.round(n / 1000)}k`)
const ago = (m: number) => (m < 120 ? `${m} min` : m < 2880 ? `${Math.round(m / 60)} h` : `${Math.round(m / 1440)} d`)
const cacheOn = () => (cfg.compact_mode === 'smart' || cfg.compact_mode === 'auto') && cfg.cache_ttl_minutes >= 15

/**
 * At each main-loop turn end: if nobody comes back before the prompt cache
 * expires, compact a few minutes before it does. Compacting re-reads the context
 * from a warm cache (cheap); a reply after expiry re-reads all of it at full price.
 */
function armCacheGuard($: EngineInterface) {
  if (!cacheOn()) return
  const seq = turnSeq, done = compactions
  $.clock.after((cfg.cache_ttl_minutes - 5) * 60000, () => { void cacheGuard($, seq, done) })
}

async function cacheGuard($: EngineInterface, seq: number, done: number) {
  if (seq !== turnSeq || done !== compactions || pending || compacting || !cacheOn()) return
  const { tokens = 0, percent = 0 } = await read($, snap)
  if (percent < snoozedTo) return // "Not now" stands
  if (tokens < cfg.cache_min_tokens) return
  if (await finishedWorker($)) return
  await update($, offer, () => null)
  await warned($, 'guard', tokens)
  coldRun = true
  $.ui.toast(`Cairn compacted before the prompt cache expired: ${k(tokens)} tokens would have been re-read at full price`)
  queueCompact($)
}

type Ends = Record<string, { at: number; tokens: number }>

/** When this session last answered, and how big it was, kept across restarts. */
async function noteEnd($: EngineInterface) {
  try {
    const sid = await $.session.id()
    const tokens = (await read($, snap)).tokens ?? 0
    const at = await $.clock.now()
    const ends = ((await $.store.get('lastEnd')) ?? {}) as Ends
    delete ends[sid]
    ends[sid] = { at, tokens }
    const keep = Object.entries(ends).slice(-30)
    await $.store.set('lastEnd', Object.fromEntries(keep))
  } catch (err) {
    $.ui.log(`cairn: could not note the turn end: ${String(err)}`)
  }
}

/**
 * At session start: a session coming back after its prompt cache expired, with
 * a big context, gets an offer to compact before the first reply re-reads it all.
 */
async function coldCheck($: EngineInterface) {
  if (cfg.compact_mode === 'off') return
  const ends = ((await $.store.get('lastEnd')) ?? {}) as Ends
  const last = ends[await $.session.id()]
  if (!last || last.tokens < cfg.cache_min_tokens) return
  const now = await $.clock.now()
  const idle = (now - last.at) / 60000
  if (idle < cfg.cache_ttl_minutes) return
  const away = idle >= 120 ? `${Math.round(idle / 60)} h` : `${Math.round(idle)} min`
  const percent = (await read($, snap)).percent ?? 0
  await warned($, 'cold', last.tokens)
  await update($, offer, () => ({
    percent, at: now, cold: true,
    reason: `away ${away}, the prompt cache expired: the next reply re-reads ${k(last.tokens)} tokens at full price, compacting first makes it and later replies cheaper`,
  }))
  // Nobody is at the screen to click the band: compact now, before the first reply re-reads it all.
  // If it can't run, the offer stays up as the fallback.
  if ((cfg.compact_mode === 'smart' || cfg.compact_mode === 'auto') && !(await finishedWorker($))) {
    $.ui.toast(`Cairn is compacting: away ${away}, the prompt cache expired`)
    tries = 0
    coldRun = true
    queueCompact($)
  }
}

async function snooze($: EngineInterface) {
  const o = await read($, offer)
  snoozedTo = (o?.percent ?? 0) + 10
  await update($, offer, () => null)
}

async function acceptOffer($: EngineInterface) {
  await update($, offer, () => null)
  tries = 0
  queueCompact($)
}

// The engine refuses a compaction under a turn a hook is holding (a command,
// a measure, a turn's end), so it is queued and run from a timer once that
// hook has let go; if a turn is running then, it waits for the turn's end.
const RETRY_MS = [400, 1500, 4000]
let pending = false
let tries = 0

function queueCompact($: EngineInterface) {
  pending = true
  if (compacting) return
  const delay = RETRY_MS[Math.min(tries, RETRY_MS.length - 1)]!
  $.clock.after(delay, () => { void runCompact($) })
}

async function runCompact($: EngineInterface) {
  if (!pending || compacting) return
  compacting = true
  cairnRun = true
  try {
    // Through the built-in /compact, not $.session.compact(): a mod's own call skips
    // the mod's own session.compact hook, which is where Cairn's notes go in.
    // The engine queues it until the session is idle.
    await $.command.run({ command: 'compact', args: '' })
    pending = false
    tries = 0
    compactions++
    $.ui.toast("Compacted with Cairn's notes: see the Cairn pane")
  } catch (err) {
    tries++
    if (tries > 6) {
      pending = false
      tries = 0
      $.ui.toast("Cairn couldn't compact; try /compact instead")
      $.ui.log(`cairn: compaction gave up: ${String(err)}`)
    }
    // otherwise still pending: the turn.complete hook (or the next timer) retries
  } finally {
    compacting = false
    cairnRun = false
    coldRun = false
  }
  if (pending) queueCompact($)
}

// ------------------------------------------------------------ hooks
export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    const ran = await next(e)
    await $.command.register({ name: 'cairn', description: 'Cairn: open the pane, or `/cairn compact` to compact with Cairn\'s notes' })
    void $.ui.open({ id: PANE, title: TITLE })
    try {
      await refresh($, await $.session.usage())
    } catch (err) {
      $.ui.log(`cairn: first measure failed: ${String(err)}`)
    }
    try {
      await coldCheck($)
    } catch (err) {
      $.ui.log(`cairn: cold-start check failed: ${String(err)}`)
    }
    try {
      const evs = parseLedger(await $.fs.read(`${claudeDir($.plugin.root)}/${LEDGER_FILE}`))
      await update($, ledger, () => evs)
    } catch { /* no ledger yet */ }
    try {
      const m = parseMeasured(await $.fs.read(`${claudeDir($.plugin.root)}/${MEASURED_FILE}`))
      await update($, measured, () => measuredLines(m))
    } catch {
      await update($, measured, () => measuredLines(null))
    }
    void refreshWorkspace($, true)
    return ran
  })

  on('session.measure', async ($, e, next) => {
    await refresh($, e)
    return next(e)
  })

  on('turn.start', async ($, e, next) => {
    if (e.agentId === undefined) { turnSeq++; turnDone = '' }
    return next(e)
  })

  // Each main-loop turn end is where Cairn decides; a queued compaction that
  // met a running turn tries again here too.
  on('turn.complete', async ($, e, next) => {
    const ran = await next(e)
    if (e.agentId !== undefined) return ran
    if (pending) queueCompact($)
    else if (e.reason === 'answer') {
      try {
        await decide($)
      } catch (err) {
        $.ui.log(`cairn: compaction decision failed: ${String(err)}`)
      }
    }
    armCacheGuard($)
    await noteEnd($)
    void refreshWorkspace($)
    return ran
  })

  on('tool.call', async ($, e, next) => {
    const ran = await next(e)
    try {
      await record($, e.tool, e as unknown as Record<string, unknown>, ran)
    } catch (err) {
      $.ui.log(`cairn: could not record ${e.tool}: ${String(err)}`)
    }
    return ran
  }).catch(($, e, next) => next(e)) // never in the way: replays or runs the call as normal

  on('session.compact', async ($, e, next) => {
    const home = claudeDir($.plugin.root)
    await loadCfg($, home)
    const isSubagent = e.agentId !== undefined
    const msgs = e.messages ?? []
    const notes = isSubagent ? SUBAGENT_INSTRUCTIONS : await mainInstructions($, msgs)
    const instructions = e.instructions ? `${e.instructions}\n\n${notes}` : notes
    const trimmed = trimMessages(msgs, cfg)
    // A compaction a plugin starts may carry no list yet: pass `messages` on only when there is one.
    const { messages: _given, ...rest } = e
    const base = Array.isArray(e.messages) ? e : rest

    let fellBack = false
    let res
    try {
      res = await next({ ...base, instructions, ...(trimmed.count ? { messages: trimmed.messages } : {}) } as typeof e)
    } catch (err) {
      if (!trimmed.count) throw err
      $.ui.log(`cairn: trimmed transcript refused (${String(err)}); compacting untrimmed`)
      fellBack = true
      res = await next({ ...base, instructions } as typeof e)
    }
    if (res.skip !== undefined || e.trigger === 'precompute' || !res.messages) return res

    let check: Compaction['check'] = 'n/a'
    let messages = res.messages
    if (!isSubagent) {
      const w = await read($, work)
      const c = checkSummary(res.messages ?? [], w, stateBlock(w, await sessionNotes($), latestAsks(msgs)))
      check = c.check
      messages = c.messages
    }
    const at = await $.clock.now()
    await update($, comps, list => [...list, {
      at, trigger: e.trigger, isSubagent,
      tokensBefore: res.tokensBefore, tokensAfter: res.tokensAfter,
      trimmedCount: fellBack ? 0 : trimmed.count, trimmedChars: fellBack ? 0 : trimmed.chars,
      check, fellBack,
    }].slice(-10))
    if (!isSubagent) {
      await logEvent($, {
        kind: 'compaction', t: at, sid: safeId(await $.session.id()), by: cairnRun ? 'cairn' : 'app',
        before: res.tokensBefore, after: res.tokensAfter, ...(cairnRun && coldRun ? { cold: true } : {}),
      })
    }
    if (!isSubagent) { snoozedTo = 0; compactions++; await update($, offer, () => null) }
    return messages === res.messages ? res : { ...res, messages }
  }).catch(($, e, next) => next(e)) // on any failure, the engine's own compaction stands

  on('command.run', { command: 'cairn' }, async ($, e) => {
    if (e.args.trim() === 'compact') {
      if (pending || compacting) return { text: 'A Cairn compaction is already queued.' }
      await acceptOffer($)
      return { text: "Compaction queued: it runs with Cairn's notes as soon as this command finishes." }
    }
    await refresh($, await $.session.usage())
    await refreshWorkspace($, true)
    const opened = await $.ui.open({ id: PANE, title: TITLE })
    return { text: opened.isPlaced ? 'Cairn pane opened.' : `Cairn pane is waiting: ${opened.reason}` }
  })

  // ---------------------------------------------------------- band (5)
  on('ui.render', { component: 'AbovePrompt' }, async ($, e, next) => {
    const o = await read($, offer)
    if (!o || e.props.hasSurvey || e.props.isWorking || pending || compacting) return next(e)
    const { Box, Button, Text } = $.ui.resolve(e)
    const idle = cfg.compact_mode === 'smart' && !o.cold ? ` · runs by itself in ${cfg.idle_minutes} min if you're away` : ''
    const say = o.cold ? `Cairn: compact before you continue (${o.reason})` : `Cairn: good moment to compact (${o.reason})`
    return (
      <Box>
        <Text>{say}{idle} </Text>
        <Button key="now" label="Compact now" onPress={() => acceptOffer($)} />
        <Text> </Text>
        <Button key="later" label="Not now" onPress={() => snooze($)} />
      </Box>
    )
  })

  // ---------------------------------------------------------- pane (7)
  // Default view: what needs you, what runs, plan health. Everything else is under Details.
  on('ui.render', { component: 'Pane', requestId: PANE }, async ($, e) => {
    const { Box, Text, Button } = $.ui.resolve(e)
    const s = await read($, snap)
    const w = await read($, work)
    const cs = await read($, comps)
    const o = await read($, offer)
    const w2 = await read($, ws)
    const dd = await read($, days)
    const led = await read($, ledger)
    const meas = await read($, measured)
    const open = await read($, details)
    const now = await $.clock.now()
    const p = s.percent
    const color = s.level === 2 ? 'red' : s.level === 1 ? 'yellow' : 'green'
    const width = 20
    const filled = p === undefined ? 0 : Math.min(width, Math.round((p / 100) * width))
    const fh = pct(s.limits, 'five_hour'), sd = pct(s.limits, 'seven_day')
    const usageHigh = (fh ?? 0) >= cfg.usage_warn || (sd ?? 0) >= cfg.usage_warn
    const { needs, running } = needsAndRunning(w2, s.inbox)
    const hl = health(s, led, now, cfg.usage_warn, cfg)
    const tip = advice(hl, s)
    const row = (it: Item, mark: string, hot: boolean) => (
      <Box flexDirection="column">
        <Text color={hot ? 'yellow' : undefined}>{mark} {it.text}</Text>
        {it.hint && <Text dimColor>   {it.hint}</Text>}
      </Box>
    )
    const barW = 16
    const barN = fh === undefined ? 0 : Math.min(barW, Math.round((fh / 100) * barW))
    return (
      <Box flexDirection="column">
        <Text bold>Needs you</Text>
        {needs.length === 0 ? <Text dimColor>Nothing needs you.</Text> : needs.map(n => row(n, '!', true))}
        <Text> </Text>
        <Text bold>Running now</Text>
        {running.length === 0 ? <Text dimColor>Nothing is running.</Text> : running.map(n => row(n, '●', false))}
        <Text> </Text>
        <Text bold>Your plan</Text>
        {fh === undefined
          ? <Text dimColor>No usage reading yet.</Text>
          : <Text color={hl.level === 'high' ? 'yellow' : undefined}>{'█'.repeat(barN)}{'░'.repeat(barW - barN)} {fh.toFixed(0)}% of your 5-hour limit used</Text>}
        {hl.saved && <Text dimColor>{hl.saved}</Text>}
        {tip && <Text color="yellow">{tip}</Text>}
        <Text> </Text>
        <Button key="details" label={open ? '▾ Hide details' : '▸ Details'} onPress={() => update($, details, v => !v)} />
        {open && (
          <Box flexDirection="column">
            <Text> </Text>
          <Text bold>Context</Text>
          {p === undefined
            ? <Text dimColor>No reading yet (fills in after the first reply).</Text>
            : <Text color={color}>{'█'.repeat(filled)}{'░'.repeat(width - filled)} {p.toFixed(0)}%</Text>}
          {s.tokens !== undefined && s.window > 0 &&
            <Text dimColor>{k(s.tokens)} of {k(s.window)} tokens · compact {cfg.compact_mode}: done-task {cfg.compact_soft}% · calm {cfg.compact_at}% · hard {cfg.compact_hard}%</Text>}
          <Text> </Text>
          <Text bold>Plan usage</Text>
          {fh === undefined && sd === undefined
            ? <Text dimColor>No rate-limit reading.</Text>
            : <Text color={usageHigh ? 'yellow' : undefined}>5h {fh?.toFixed(0) ?? '–'}% · 7d {sd?.toFixed(0) ?? '–'}%</Text>}
          {s.usd !== undefined && <Text dimColor>Session cost ${s.usd.toFixed(2)}</Text>}
          {Object.keys(dd).slice(-4).reverse().map(k => (
            <Text dimColor>
              {dayLine(k, dd[k]!)}
            </Text>
          ))}
          <Text> </Text>
          <Text bold>Savings</Text>
          {summaryLines(led, dd, now, cfg).map((l, i) => (
            <Text dimColor={i > 0 && l.startsWith('Estimate')}>{l}</Text>
          ))}
          {meas.map((l, i) => (
            <Text color={i === 0 ? 'cyan' : undefined} dimColor={i > 0}>{l}</Text>
          ))}
          <Text> </Text>
          <Text bold>Work tracked</Text>
          <Text dimColor>{w.files.length} files edited · {w.oks.length} recent commands ok</Text>
          {editsBehind(w.files) >= 6 &&
            <Text color="yellow">SESSION.md is {editsBehind(w.files)} edits behind: save the state with handoff.</Text>}
          {w.fails.length > 0 && <Text color="yellow">Open failures: {w.fails.map(f => f.cmd.slice(0, 40)).join(' · ')}</Text>}
          <Text> </Text>
          <Text bold>Compactions</Text>
          {cs.length === 0
            ? <Text dimColor>None yet this session.</Text>
            : cs.slice(-3).map(c => (
              <Text dimColor={c.check !== 'patched'}>
                {c.trigger}{c.isSubagent ? ' (subagent)' : ''}: {k(c.tokensBefore)} → {k(c.tokensAfter)} · trimmed {c.trimmedCount} ({k(c.trimmedChars / 4)} tok) · check {c.check}{c.fellBack ? ' · trim refused' : ''}
              </Text>
            ))}
          <Text> </Text>
          <Text bold>Workspace</Text>
          {!w2
            ? <Text dimColor>Loading (cairn.py workspace)…</Text>
            : w2.repos.map(r => {
              const live = r.sessions.filter(x => x.status === 'busy' || x.status === 'idle' || x.status === 'waiting')
              return (
                <Box flexDirection="column">
                  <Text>{r.name}{r.notes ? ` · ${r.notes} note(s) waiting` : ''}{r.worktrees ? ` · ${r.worktrees} worktree(s)` : ''}</Text>
                  <Text dimColor>  goal: {r.goal ? r.goal.slice(0, 70) : 'none set'}</Text>
                  {live.map(x => (
                    <Text color={x.status === 'waiting' ? 'yellow' : undefined} dimColor={x.status === 'idle' && !x.warm}>
                      {'  '}{x.status === 'busy' ? '●' : x.status === 'waiting' ? '!' : '○'} {x.title.slice(0, 40)} · {x.status} · {k(x.tokens ?? undefined)} · cache {x.warm ? 'warm' : 'cold'}
                    </Text>
                  ))}
                  {live.length === 0 && <Text dimColor>  no live session{r.sessions.length ? ` · last ${ago(r.sessions[0]!.ageMin)} ago` : ''}</Text>}
                </Box>
              )
            })}
          {w2 && (w2.board ?? []).length > 0 && (() => {
            const b = w2.board ?? []
            const open = b.filter(t => t.status !== 'done' && t.status !== 'closed')
            const done = b.filter(t => t.status === 'done').slice(0, 3)
            return (
              <Box flexDirection="column">
                <Text>Board (Cairn Home) · {open.filter(t => t.status === 'running').length} running · {open.filter(t => t.status === 'waiting').length} waiting on you</Text>
                {[...open, ...done].map(t => (
                  <Text color={t.status === 'waiting' ? 'yellow' : undefined} dimColor={t.status === 'done' || t.status === 'queued'}>
                    {'  '}{t.status === 'running' ? '●' : t.status === 'waiting' ? '!' : t.status === 'queued' ? '…' : '✓'} {t.id} {t.title.slice(0, 40)} · {t.status} · {t.model}/{t.effort}{t.status === 'running' && (w2.at - t.updated) / 60 >= 90 ? ` · quiet ${ago(Math.round((w2.at - t.updated) / 60))}, check it` : ''}{t.report ? ` · ${t.report.slice(0, 50)}` : ''}
                  </Text>
                ))}
              </Box>
            )
          })()}
          {w2 && (w2.stale ?? []).length > 0 &&
            <Text color="yellow">Stale: {(w2.stale ?? []).map(s => `${s.name} ${s.worktrees.length} worktree(s)${s.worktrees.some(x => x.dirty) ? ' (uncommitted!)' : ''}, ${s.oldSessions} old session(s)`).join(' · ')}. Ask Cairn to clean up.</Text>}
          {w2 && w2.unregistered.length > 0 &&
            <Text dimColor>Not in REPOS.md: {w2.unregistered.map(u => `${u.title.slice(0, 30)} (${u.status})`).join(' · ')}</Text>}
          <Text> </Text>
          <Text bold>Inbox</Text>
          {s.inbox.length === 0
            ? <Text dimColor>No notes waiting.</Text>
            : <Text color="yellow">Notes waiting for: {s.inbox.join(', ')}</Text>}
          </Box>
        )}
      </Box>
    )
  })
}
