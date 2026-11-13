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
  /** ok: summary kept the edited files; patched: Coach added them; n/a: nothing to check */
  check: 'ok' | 'patched' | 'n/a'
  /** trimming was refused by the engine and the untrimmed transcript was used */
  fellBack: boolean
}

/** A compaction Coach is offering in the band above the prompt. */
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

declare module 'claude-code' {
  interface PluginState {
    'coach-watcher': {
      snap: Shaped<Snap>
      work: Shaped<Work>
      comps: Shaped<Compaction[]>
      offer: Shaped<Offer | null>
    }
  }
}
