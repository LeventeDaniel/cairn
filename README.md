# coach-watcher

Companion mod for Context Coach. It shows a live **Context Coach** pane (context fill, plan usage, cost, work tracked, recent compactions, inbox notes) and a status entry, and it makes compaction keep what matters.

## What it does

- **Tracks the work** as tool calls finish: files edited, commands that failed (until they pass again), recent commands that worked.
- **Guides every compaction** (auto, `/compact`, or `/coach compact`): the summarizer is told the goal and next steps from `SESSION.md`, the files edited, open failures and your latest requests. Text you type after `/compact` comes first.
- **Trims bulky tool results** (whole-file reads, long logs, search dumps) to a head and tail before summarizing. If the engine refuses the trimmed copy, it compacts the untrimmed transcript instead.
- **Checks the summary**: if it dropped the recently edited files, Coach appends its state block to the summary.
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
- **Feeds coach.py** exact numbers in `~/.claude/coach/state/<session>.json`, because the Code tab runs no status line.

## Commands

- `/coach` opens the pane.
- `/coach compact` queues a compaction with Coach's notes. It runs through the built-in `/compact` as soon as the command finishes, and retries after the current turn if one is still running.

## Settings

These go in `~/.claude/coach/config.json`, next to Context Coach's own keys:

| key | default | meaning |
|---|---|---|
| `compact_mode` | `smart` | `smart` (Coach decides), `ask` (offers only), `auto` (compacts at `compact_at` whatever the state) or `off` |
| `compact_soft` | `40` | % from which a finished piece of work is a reason to compact |
| `compact_at` | `60` | % from which any calm turn end is |
| `compact_hard` | `72` | % at which it compacts at the next turn end, mid-task or not |
| `idle_minutes` | `3` | an unanswered offer runs after this many minutes with no new prompt |
| `cache_ttl_minutes` | `60` | how long the prompt cache lasts after a reply (60 on plans with the 1-hour cache; set 5 if you're in usage overage). Below 15 the idle cache guard is off |
| `cache_min_tokens` | `60000` | contexts smaller than this are cheap to re-read cold, so the cache checks leave them alone |
| `trim_over` | `4000` | tool results longer than this many characters get trimmed (errors: 4×) |
| `trim_keep` | `800` | characters kept from a trimmed result |
| `warn` / `urgent` / `usage_warn` | `50` / `70` / `80` | shared with Context Coach |

## Install

At the prompt of a Claude Code terminal session:

```
/plugin install coach-watcher --marketplace LeventeDaniel/context-watcher
```

Answer `y` to add the marketplace, then pick a scope (user is first).

From a shell:

```
claude plugin install coach-watcher --marketplace LeventeDaniel/context-watcher
```

In the desktop app, where `/plugin` does not run: click + next to the prompt box, then Plugins, Add marketplace with `LeventeDaniel/context-watcher`, then Add plugin.

The pane and compaction help work on their own. The `SESSION.md` notes, inbox and shared thresholds come from Context Coach, if you have it installed in `~/.claude/coach/`.

## License

MIT
