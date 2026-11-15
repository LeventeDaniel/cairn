# cairn

Companion mod for Cairn. It shows a live **Cairn** pane and a status entry, and it makes compaction keep what matters.

## The pane

By default the pane shows three things, in plain words:

- **Needs you**: sessions or board tasks waiting for your answer, one line each ("Nothing needs you." when clear), plus notes waiting in the inbox.
- **Running now**: sessions working at the moment, one line each.
- **Your plan**: a bar and "N% of your 5-hour limit used". Under it, "Cairn so far: …": the verdict of `cairn.py stats`, counted, never estimated (see Results below). One short advice sentence appears only when you should act (plan nearly used, chat very long).

Press **▸ Details** (closed by default) for everything else: context breakdown and compaction thresholds, usage per day, the counted results, work tracked, compaction history, workspace per repo, board, stale cleanup and inbox. Session lines are plain text for now: the pane cannot link to a desktop session.

## What it does

- **Tracks the work** as tool calls finish: files edited, commands that failed (until they pass again), recent commands that worked.
- **Guides every compaction** (auto, `/compact`, or `/cairn compact`): the summarizer is told the goal and next steps from `SESSION.md`, the files edited, open failures and your latest requests. Text you type after `/compact` comes first.
- **Trims bulky tool results** (whole-file reads, long logs, search dumps) to a head and tail before summarizing. If the engine refuses the trimmed copy, it compacts the untrimmed transcript instead.
- **Checks the summary**: if it dropped the recently edited files, Cairn appends its state block to the summary.
- **Subagent compactions** keep only the task, findings with file:line, and conclusions.
- **Decides when to compact** (`smart`, the default). At the end of each turn it looks at how full the context is and what just happened:
  - a finished piece of work (the task wrapped up, a commit or push, a failing command passing again) from `compact_soft` → it compacts once you have been away `idle_minutes` (a new prompt before that calls it off)
  - the same from `compact_at` → it compacts right away
  - any other calm turn end from `compact_at` → it compacts once you have been away `idle_minutes`
  - an open failure (you are mid-debug) → it waits, until `compact_hard`
  - at `compact_hard` → it compacts at the turn end, so the engine's own auto-compact never cuts in mid-task
  It never asks: there is no band and no "compact now?" choice. A planned compaction is one dim line in the pane, and a finished one is one toast saying why it ran. `/cairn compact` runs one on demand.
- **Watches the prompt cache** (`smart` and `auto`). A reply re-reads the whole context; inside the cache window that read is cheap, after it the full context is read again at full price.
  - left idle with at least `cache_min_tokens` in context, it compacts 5 minutes before the cache expires, while compacting is still cheap
  - a session resumed after the cache expired is left alone at its start (after an app restart every session starts at once, and compacting them all cold is a full-price read each). The first reply runs on the full context, is logged as a cold re-read, and the turn end after it decides as usual, from a warm cache. A worker whose task is finished gets one pane line saying to archive it
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
| `compact_mode` | `smart` | `smart` (Cairn decides and acts by itself, it never asks), `auto` (compacts at `compact_at` whatever the state) or `off`. `ask` from older configs is read as `smart` |
| `compact_soft` | `40` | % from which a finished piece of work is a reason to compact |
| `compact_at` | `60` | % from which any calm turn end is |
| `compact_hard` | `72` | % at which it compacts at the next turn end, mid-task or not |
| `compact_soft_tokens` / `compact_at_tokens` / `compact_hard_tokens` | `100000` / `200000` / `400000` | the same three steps as token counts; whichever comes first applies (on a 1M-token window the percentages alone are 400k / 600k / 720k). `0` = percentage only |
| `compact_min_gain_tokens` | `60000` | a compaction cannot go below the floor (system prompt, tools, skills, the summary, re-attached files: often 60-90k tokens). Cairn learns the floor from the first reply after each compaction and lifts any step that sits under floor + this much; near the floor there is nothing to remove and the compaction itself costs a new cache write. `0` = steps as configured |
| `usage_stop` | `95` | from this % of the 5-hour or weekly limit Cairn starts no compaction by itself (at the limit it can only fail). `/cairn compact` still works |
| `idle_minutes` | `3` | a compaction planned at a clean break runs after this many minutes with no new prompt |
| `cache_ttl_minutes` | `60` | how long the prompt cache lasts after a reply. Taken from Claude Code's `promptCacheTtl` setting (`5m` / `1h`) when that is set. Below 15 the idle cache guard is off, and Claude Code's own `idleCompaction` covers idle sessions |
| `cache_min_tokens` | `60000` | contexts smaller than this are cheap to re-read cold, so the cache checks leave them alone |
| `trim_over` | `4000` | tool results longer than this many characters get trimmed (errors: 4×) |
| `trim_keep` | `800` | characters kept from a trimmed result |
| `home_compact_soft` / `home_compact_at` / `home_compact_hard` | `15` / `25` / `50` | the three thresholds above, for a session in Cairn Home's folder |
| `home_compact_soft_tokens` / `home_compact_at_tokens` / `home_compact_hard_tokens` | `50000` / `80000` / `150000` | the token steps for Cairn Home; lifted above the floor like the others |
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

The pane and compaction help work on their own. The `SESSION.md` notes, inbox and shared thresholds come from the Cairn kit in [`kit/`](kit/README.md) (skills, agents, `cairn.py`, the CLAUDE.md block). Install it with `python install.py` from that folder; it needs only Python 3.8+.

## License

MIT

## Results: is it worth running?

`python ~/.claude/cairn/cairn.py stats` answers that with counted numbers and one verdict (`USEFUL`, `ABOUT BREAK-EVEN`, `NOT USEFUL SO FAR` or `NOT PROVEN`). The pane shows the same: the verdict under **Your plan**, the lines under Details. Nothing is estimated; what cannot be counted says "not measured".

- **Compactions**: from the transcripts, per compaction: the context before, the context of the first reply after, and how many replies really followed. Avoided = tokens removed x replies that followed. Cost = the history the summary read (x10 when the prompt cache had expired and nobody came back) + the cache the next reply had to write again (a cache write costs 12.5-20 cached reads) + Cairn's own text in every reply (its size comes from the A/B run). Cairn is credited only with the compactions its ledger (`~/.claude/cairn/state/ledger.json`) says it started.
- **Startup**: Claude Code's own count of a new session (`claude -p /context`, free, read at most once a day into `state/baseline.json`), first reading against the latest, and the median first reply of real sessions.
- **Tasks**: routed by Cairn Home, finished, dispatch-to-done time (recorded when a task is reported done; kept in `state/tally.json` after the row leaves the board), finished workers closed, usage-limit hits (from the transcripts) and workers stopped by an API error.
- **A/B**: the benchmark runs in `bench/` (`bench/run.py`, `bench/scenario.py`) write `state/measured.json`; `stats` quotes them next to the live numbers. See `bench/RESULTS.md`.

`stats --days N` changes the window (default 30), `--json` prints everything including a per-session table.
