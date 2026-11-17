---
name: route
description: Where a new instruction runs and the exact commands to start a session elsewhere (other repo, new project, background, cloud, Claude Code Project, schedule, durable rule). Use when a new instruction is NOT a plain continuation of this session's goal, before starting or sending anything.
---
Pick the row, then act on it yourself. Start your reply with `↪ <what you did> — <why in ≤12 words>`.

| The instruction… | What you do on your own |
|---|---|
| Continues this session's goal | do it here |
| Same goal, heavy searching/reading/research | here, via `scout` / `researcher` subagents |
| Hard design call, or stuck after 2 tries | here, via `architect` subagent |
| Independent task in this repo (or unrelated to this session's goal) | in the desktop Code tab, start it with the app's own session tool (name it `<repo>: <task>`); in a terminal, start a background session: `{{SPAWN}} --where bg --name <short-name> --from-session "<this repo>: <goal>" --task "<self-contained task + needed context>"` (add `--model haiku` or `--model sonnet` when the task is simple; without it the session runs on my main model) |
| Belongs to another repo in `~/.claude/REPOS.md` | same command with `--repo <that repo's path>`; if it's only info, not a task, `pass` it instead |
| A new project that has no repo yet | same command with `--new-repo "<one-line purpose>" --name <kebab-name>` (creates the folder, git init, registers it, starts the session) |
| Long/unattended, repo has a GitHub remote, needs nothing local-only | same command with `--where cloud` |
| A stream of related tasks to farm out in parallel | suggest a Claude Code Project in one line, with a name and its first instruction written out (can't be created from here) |
| Should repeat on a schedule | write the exact routine (prompt + schedule) and say where to paste it |
| A durable fact or standing rule, not a task | save to auto memory or this CLAUDE.md yourself |

Rules for starting sessions: write `--task` so it stands alone (the new session can't see this chat) and say what files/branch to use. Background sessions stop and wait if they hit a permission prompt; tell me in one line if the task will need approvals. Never start one for destructive or irreversible work, or for anything I said to do here. If the command prints REFUSED or CANNOT START, follow its message. Cloud sessions don't get my `~/.claude` setup — only what's committed in the repo.

Also: after any multi-step procedure that could recur, append `- YYYY-MM-DD | <repo> | <short procedure name>` to `~/.claude/cairn/procedures.md`; at 3 repeats draft the skill with `skill-scout`.

## Delegation, models, effort
`scout` = Haiku, `researcher` = Sonnet, `architect` = my main model. Run independent subagents in parallel; bring back summaries only. Heavy searching/reading → `scout`/`researcher`; hard design or stuck after 2 tries → `architect`. If my main model is a poor fit, say which to pick with `/model` in one line.

## Memory, repos
- SESSION.md = task state; auto memory = durable facts; CLAUDE.md = standing rules; another repo → `pass`.
- Sessions you started report back by message or as `[Cairn] New notes`; tell me in one line each.
- If sessions start heavy, run `context-audit` yourself. When you route, spawn, hand off or save a rule, say so in ONE line; for plain task work add no Cairn commentary.
