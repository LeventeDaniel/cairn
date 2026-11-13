# coach-watcher

Companion mod for Context Coach. It shows a live **Context Coach** pane (context fill, plan usage, cost, work tracked, recent compactions, inbox notes) and a status entry, and it makes compaction keep what matters.

## What it does

- **Tracks the work** as tool calls finish: files edited, commands that failed (until they pass again), recent commands that worked.
- **Guides every compaction** (auto, `/compact`, or `/coach compact`): the summarizer is told the goal and next steps from `SESSION.md`, the files edited, open failures and your latest requests. Text you type after `/compact` comes first.
- **Trims bulky tool results** (whole-file reads, long logs, search dumps) to a head and tail before summarizing. If the engine refuses the trimmed copy, it compacts the untrimmed transcript instead.
- **Checks the summary**: if it dropped the recently edited files, Coach appends its state block to the summary.
- **Subagent compactions** keep only the task, findings with file:line, and conclusions.
- **Clean-break compaction**: once context passes `compact_at`, it offers (`ask`) or runs (`auto`) a guided compaction between turns.
- **Feeds coach.py** exact numbers in `~/.claude/coach/state/<session>.json`, because the Code tab runs no status line.

## Commands

- `/coach` opens the pane.
- `/coach compact` queues a compaction with Coach's notes. It runs through the built-in `/compact` as soon as the command finishes, and retries after the current turn if one is still running.

## Settings

These go in `~/.claude/coach/config.json`, next to Context Coach's own keys:

| key | default | meaning |
|---|---|---|
| `compact_mode` | `ask` | `ask`, `auto` or `off`, for the clean-break compaction |
| `compact_at` | `60` | % of context at which it is offered or run |
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
