---
name: repos
description: Show or tidy the repo registry (~/.claude/REPOS.md). Use when the user types /repos, asks what they're working on, or a repo line still has '?' as its purpose.
---
`~/.claude/REPOS.md` has one line per repo/folder (all git worktrees of a repo share one line):
`- <name> | <main repo path> | <one-line purpose> | <active/paused/done> | <last touched>`
(Not the same thing as Claude Code's built-in "Projects" feature — see the where-to-run skill.)

The session-start hook adds new repos and stamps "last touched" automatically. Your job:
- Fill a '?' purpose (ask the user in one line if you can't infer it from the repo).
- When asked, list repos by last touched; flag ones untouched 30+ days as candidates for "paused".
- Show pending notes: non-empty files in `~/.claude/inbox/`.
