# cairn

Companion mod for Cairn. It shows a live **Cairn** pane (context fill, plan usage, cost, work tracked, recent compactions, inbox notes) and a status entry, and it makes compaction keep what matters.

## What it does

- **Tracks the work** as tool calls finish: files edited, commands that failed (until they pass again), recent commands that worked.
- **Guides every compaction** (auto, `/compact`, or `/cairn compact`): the summarizer is told the goal and next steps from `SESSION.md`, the files edited, open failures and your latest requests. Text you type after `/compact` comes first.
- **Trims bulky tool results** (whole-file reads, long logs, search dumps) to a head and tail before summarizing. If the engine refuses the trimmed copy, it compacts the untrimmed transcript instead.
- **Checks the summary**: if it dropped the recently edited files, Cairn appends its state block to the summary.
- **Subagent compactions** keep only the task, findings with file:line, and conclusions.
- **Decides when to compact** (`smart`, the default). At the end of each turn it looks at how full the context is and what just happened:
  - a finished piece of work (the task wrapped up, a commit or push, a failing command passing again) from `compact_soft` → it offers in a band above the prompt
  - the same from `compact_at` → it compacts right away
  - any other calm turn end from `compact_at` → it offers
  - an open failure (you are mid-debug) → it waits, until `compact_hard`
  - at `compact_hard` → it compacts at the turn end, so the engine's own auto-compact never cuts in mid-task
  - an offer nobody answers runs by itself after `idle_minutes` with no new prompt, while you are away
  The band has **Compact now** and **Not now** (quiet until context grows 10 more points).
- **Watches the prompt cache** (`smart` and `auto`). A reply re-reads the whole context; inside the cache window that read is cheap, after it the full context is read again at full price.
  - left idle with at least `cache_min_tokens` in context, it compacts 5 minutes before the cache expires, while compacting is still cheap (Not now still holds)
  - a session resumed after the cache expired, with a big context, gets an offer to compact before the first reply
- **Workspace** section in the pane: every repo in `~/.claude/REPOS.md` with its goal (from SESSION.md), its live sessions (busy, idle or waiting, from `claude agents --json`), their size and whether their prompt cache is still warm, worktrees and notes waiting. It comes from `cairn.py workspace --json`, run with the same Python as Cairn's hook, at most once a minute. In a terminal: `python ~/.claude/cairn/cairn.py workspace`.
- **Board** under Workspace: the tasks Cairn Home started (`~/.claude/cairn/board.json`): running, waiting on you, queued, recently done, each with its model/effort and last one-line report.
- **Cairn Home** (a session in `~/.claude/cairn/home`) holds only the board, so it compacts much earlier: see the `home_compact_*` settings.
- **Feeds cairn.py** exact numbers in `~/.claude/cairn/state/<session>.json`, because the Code tab runs no status line.

- **Usage per day** in the pane: cost summed over all sessions and the peak 5h / 7d plan usage for the last days, kept in `~/.claude/cairn/state/usage-days.json` (14 days).
- **Handoff warning**: the pane says when `SESSION.md` is 6 or more edits behind your work.
- **Board** (Cairn Home): running, waiting and recent tasks. A toast appears in Cairn Home when a task finishes or starts waiting on you, and a running task with no news for 90 minutes is marked "quiet, check it".
- **Stale** line: worktrees and closed sessions nobody touched for 14 days (`cairn.py cleanup` lists them; nothing is removed automatically).
- The workspace view refreshes every 2 minutes while something changes, so an idle session does not show an old board.

## Commands

- `/cairn` opens the pane.
- `/cairn compact` queues a compaction with Cairn's notes. It runs through the built-in `/compact` as soon as the command finishes, and retries after the current turn if one is still running.

## Settings

These go in `~/.claude/cairn/config.json`, next to Cairn's own keys:

| key | default | meaning |
|---|---|---|
| `compact_mode` | `smart` | `smart` (Cairn decides), `ask` (offers only), `auto` (compacts at `compact_at` whatever the state) or `off` |
| `compact_soft` | `40` | % from which a finished piece of work is a reason to compact |
| `compact_at` | `60` | % from which any calm turn end is |
| `compact_hard` | `72` | % at which it compacts at the next turn end, mid-task or not |
| `idle_minutes` | `3` | an unanswered offer runs after this many minutes with no new prompt |
| `cache_ttl_minutes` | `60` | how long the prompt cache lasts after a reply. Taken from Claude Code's `promptCacheTtl` setting (`5m` / `1h`) when that is set. Below 15 the idle cache guard is off, and Claude Code's own `idleCompaction` covers idle sessions |
| `cache_min_tokens` | `60000` | contexts smaller than this are cheap to re-read cold, so the cache checks leave them alone |
| `trim_over` | `4000` | tool results longer than this many characters get trimmed (errors: 4×) |
| `trim_keep` | `800` | characters kept from a trimmed result |
| `home_compact_soft` / `home_compact_at` / `home_compact_hard` | `15` / `25` / `50` | the three thresholds above, for a session in Cairn Home's folder |
| `warn` / `urgent` / `usage_warn` | `50` / `70` / `80` | shared with Cairn |

## Install

At the prompt of a Claude Code terminal session:

```
/plugin install cairn --marketplace LeventeDaniel/cairn
```

Answer `y` to add the marketplace, then pick a scope (user is first).

From a shell:

```
claude plugin install cairn --marketplace LeventeDaniel/cairn
```

In the desktop app, where `/plugin` does not run: click + next to the prompt box, then Plugins, Add marketplace with `LeventeDaniel/cairn`, then Add plugin.

The pane and compaction help work on their own. The `SESSION.md` notes, inbox and shared thresholds come from Cairn, if you have it installed in `~/.claude/cairn/`.

## License

MIT

## Savings ledger

Cairn logs each main-session compaction (tokens before and after, and whether Cairn or the app triggered it) and each cache-expired warning (and whether you compacted after it) to `~/.claude/cairn/state/ledger.json` (last 500 events). The pane's **Savings** section sums the last 7 days. Savings are an **estimate**, not a measurement: only compactions Cairn triggered count, each assumed to spare `ledger_turns` (10) later replies from re-reading the removed tokens at `ledger_read_usd_per_mtok` ($0.30/Mtok), plus the one full-price re-read (`ledger_write_usd_per_mtok`, $3.75/Mtok) avoided when the cache was cold. All three are tunable in `config.json`. The cost-per-session comparison before vs after the first ledger event needs 3+ sessions on each side in `usage-days.json`; otherwise the pane says there is not enough data.
