<!-- cairn:start -->
## Cairn — session manager (keep this block; reinstall replaces it)
**Act, don't ask.** Never ask me to type a slash command except `/clear`. Use the kit's skills (handoff, pass, repos, where-to-run, context-audit, skill-scout, cairn-update) yourself whenever they fit. When you route, spawn, hand off or save a rule, say so in ONE line. For plain task work add no Cairn commentary.
- Relay any `[Cairn]` note in one line at the top of your reply, and act on it.
- Context filling up → with the cairn mod running, it compacts at clean breaks: just keep SESSION.md current (run `handoff` if it is stale). Without it, run `handoff` yourself, then tell me "type /clear".

### Routing — check EVERY new instruction before doing it
If it belongs here, just do it, silently. **If in doubt, do it here.** When this session has no goal yet, the first instruction sets the goal (route: here). Only when you send it elsewhere, start your reply with:
`↪ <what you did> — <why in ≤12 words>`

| The instruction… | What you do on your own |
|---|---|
| Continues this session's goal | do it here |
| Same goal, heavy searching/reading/research | here, via `scout` / `researcher` subagents |
| Hard design call, or stuck after 2 tries | here, via `architect` subagent |
| Independent task in this repo (or unrelated to this session's goal) | in the desktop Code tab, start it with the app's own session tool (name it `<repo>: <task>`); in a terminal, start a background session: `{{SPAWN}} --where bg --name <short-name> --from-session "<this repo>: <goal>" --task "<self-contained task + needed context>"` |
| Belongs to another repo in `~/.claude/REPOS.md` | same command with `--repo <that repo's path>`; if it's only info, not a task, `pass` it instead |
| A new project that has no repo yet | same command with `--new-repo "<one-line purpose>" --name <kebab-name>` (creates the folder, git init, registers it, starts the session) |
| Long/unattended, repo has a GitHub remote, needs nothing local-only | same command with `--where cloud` |
| A stream of related tasks to farm out in parallel | suggest a Claude Code Project in one line, with a name and its first instruction written out (can't be created from here) |
| Should repeat on a schedule | write the exact routine (prompt + schedule) and say where to paste it |
| A durable fact or standing rule, not a task | save to auto memory or this CLAUDE.md yourself |

Rules for starting sessions: write `--task` so it stands alone (the new session can't see this chat) and say what files/branch to use. Background sessions stop and wait if they hit a permission prompt; tell me in one line if the task will need approvals. Never start one for destructive or irreversible work, or for anything I said to do here. If the command prints REFUSED or CANNOT START, follow its message. Cloud sessions don't get my `~/.claude` setup — only what's committed in the repo.

### Delegation, models, effort — decide yourself
- `scout` = Haiku, low effort. `researcher` = Sonnet. `architect` = my main model, high effort. Run independent subagents in parallel; bring back summaries only.
- If my main model is a poor fit (routine edits on a top model, hard design on a small one, usage near limits), say which to pick with `/model` in one line.

### Memory, repos, skills
- Session lifecycle: one task per session, titled `<repo>: <task>`. When this session's goal is done (committed or pushed, nothing waiting on me), offer Archive once (in the Code tab, the wrap-up's archive action), after a handoff if SESSION.md is stale.
- What goes where: SESSION.md = current task state; auto memory = durable project facts; this CLAUDE.md = standing rules; another repo → `pass`.
- Sessions you started report back by message (or, if they can't, as `[Cairn] New notes` on my next message); tell me in one line each. Cloud sessions report in their final message at claude.ai/code.
- After any multi-step procedure that could recur, append `- YYYY-MM-DD | <repo> | <short procedure name>` to `~/.claude/cairn/procedures.md`. At 3 repeats, draft the skill with `skill-scout` yourself and tell me.
- If sessions start heavy, run `context-audit` yourself and propose the trims.
- To see the user's screen, run `cairn.py shot` then Read the PNG; never ask the user for screenshots.

## Compact instructions
When compacting, keep: current goal, decisions, files edited, failing tests/errors, next steps.
<!-- cairn:end -->
