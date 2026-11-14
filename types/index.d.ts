export type Limit = { kind: string; percentUsed: number }

export type Snap = {
  /** context fill 0-100, absent until the first response of the live window */
  percent?: number
  tokens?: number
  window: number
  limits: Limit[]
  usd?: number
  /** 0 ok, 1 past warn, 2 past urgent */
  level: number
  /** inbox files with notes waiting */
  inbox: string[]
  at: number
}

export type Fail = { cmd: string; error: string; at: number }

/** What the session has done, recorded from tool calls as they finish. */
export type Work = {
  /** files edited or written, most recent last */
  files: string[]
  /** failed commands not yet seen succeeding, most recent last */
  fails: Fail[]
  /** recent successful commands, most recent last */
  oks: string[]
}

export type Compaction = {
  at: number
  trigger: string
  isSubagent: boolean
  tokensBefore?: number
  tokensAfter?: number
  trimmedCount: number
  trimmedChars: number
  /** ok: summary kept the edited files; patched: Cairn added them; n/a: nothing to check */
  check: 'ok' | 'patched' | 'n/a'
  /** trimming was refused by the engine and the untrimmed transcript was used */
  fellBack: boolean
}

/** A compaction Cairn is offering in the band above the prompt. */
export type Offer = {
  /** context % when offered */
  percent: number
  /** why now, in a few words */
  reason: string
  /** clock time of the offer */
  at: number
  /** offered at session start because the prompt cache expired while away */
  cold?: boolean
}

/** One session of a repo, as `cairn.py workspace` reads it. */
export type WsSession = {
  id: string
  title: string
  /** busy, idle or waiting while it runs (from `claude agents`); closed otherwise */
  status: string
  kind?: string | null
  ageMin: number
  tokens?: number | null
  /** last activity inside the prompt cache TTL */
  warm: boolean
}

/** Every registered repo at a glance (REPOS.md, SESSION.md, transcripts, `claude agents`). */
export type Workspace = {
  at: number
  cacheTtlMin: number
  repos: {
    name: string; path: string; purpose: string; goal: string; next: string
    sessions: WsSession[]; notes: number; worktrees: number
  }[]
  unregistered: { title: string; cwd?: string | null; status?: string | null; kind?: string | null }[]
  board?: BoardTask[]
  stale?: { name: string; worktrees: { path: string; branch: string; dirty: boolean; ageDays: number }[]; oldSessions: number }[]
}

/** A row of Cairn Home's task board (~/.claude/cairn/board.json), via `cairn.py workspace --json`. */
export type BoardTask = {
  id: string; repo: string; title: string; kind: string; model: string; effort: string
  session: string; cliSession?: string
  status: 'running' | 'waiting' | 'done' | 'queued' | 'closed'
  started: number; updated: number; report: string; reportStale?: boolean
}

declare module 'claude-code' {
  interface PluginState {
    'cairn': {
      snap: Shaped<Snap>
      work: Shaped<Work>
      comps: Shaped<Compaction[]>
      offer: Shaped<Offer | null>
      ws: Shaped<Workspace | null>
      details: Shaped<boolean>
      ledger: Shaped<import('../hooks/ledger').LedgerEvent[]>
    }
  }
}
