---
name: where-to-run
description: Explain and choose between local, background, worktree, cloud, Remote Control, Claude Code Projects, subagents and scheduled tasks. Use when the user asks where/how to run something, is confused about local vs cloud, or the Routing rules say a task belongs elsewhere.
---
Answer in plain words, recommend ONE option first, then one line on the runner-up. Offer to set it up (write the prompt, handoff or note).

## The options (Claude Code, Nov 2026 — re-check with cairn-update)
- **Local session** — Code tab "Local" or terminal. Runs on this computer with all its files, tools, secrets and the user's `~/.claude` setup (Cairn, skills, agents). Stops if the computer sleeps or the app closes.
- **Subagent** — a helper inside the current session with its own context; only its summary comes back. For heavy reading/search/research within one task.
- **Background session + worktree** — a separate local session on its own branch/folder (Code tab: new session with a worktree; terminal: `claude --bg "<task>"`, watch with `claude agents`). For independent work in the same repo without file clashes. Needs the computer on.
- **Cloud session** — Code tab "Cloud", claude.ai/code, phone, or `claude --cloud`. Fresh VM per task, clones the repo from GitHub, keeps running with the laptop closed, can run many in parallel. Does NOT have local files, local tools/secrets, or `~/.claude` config — only what's committed in the repo. Push local commits first. Pull it back to the computer with `/teleport` (`claude --teleport`).
- **Remote Control** — a local session you drive from phone/browser (`/remote-control` in a session). Has local files; stops if the computer sleeps.
- **Projects** in Claude Code (beta on Pro/Max/Ultra; in the claude.ai/code sidebar and the Code tab, under More if hidden; not the same as chat Projects or `~/.claude/REPOS.md`) — one coordinating conversation that splits a stream of related work into parallel threads (cloud sessions) with shared instructions and memory. Uses limits fast.
- **Agent teams** (experimental) — sessions that message each other and share a task list. Costly; only for big coordinated builds.
- **Scheduled tasks** — cloud scheduled tasks (formerly routines) run without the computer and belong to the signed-in account; desktop scheduled tasks run locally and need the app open and the computer awake.

## Quick decision
1. Needs this computer's files/tools/secrets? → local (+ Remote Control to follow from the phone, background session for parallel work).
2. Otherwise, long or unattended, or several at once? → cloud session; a stream of related tasks → Claude Code Project.
3. Just heavy reading inside the current task? → subagent.
4. Repeats on a schedule? → scheduled task (cloud if it needs no local files).
