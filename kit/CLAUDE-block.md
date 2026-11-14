<!-- cairn:start -->
## Cairn — session manager (keep this block; reinstall replaces it)
**Act, don't ask.** Never ask me to type a slash command except `/clear`. Use the kit's skills (route, handoff, pass, repos, where-to-run, context-audit, skill-scout, cairn-update) yourself whenever they fit. When you route, spawn, hand off or save a rule, say so in ONE line. For plain task work add no Cairn commentary.
- Relay any `[Cairn]` note in one line at the top of your reply, and act on it.
- Context filling up → with the cairn mod running, it compacts at clean breaks: keep SESSION.md current (run `handoff` if stale). Without it, run `handoff`, then tell me "type /clear".

### Routing
Check every new instruction. **If in doubt, do it here.** The first instruction of a session sets its goal. Continuing the goal → do it here, silently. Heavy searching/reading → `scout`/`researcher` subagent; hard design or stuck after 2 tries → `architect` subagent. Anything else (independent task, another repo, new project, long/unattended, scheduled, durable rule) → invoke the `route` skill first, it has the commands.

### Delegation, models, effort
`scout` = Haiku, `researcher` = Sonnet, `architect` = my main model. Run independent subagents in parallel; bring back summaries only. If my main model is a poor fit, say which to pick with `/model` in one line.

### Memory, repos
- One task per session, titled `<repo>: <task>`; when its goal is done, offer Archive once (after a handoff if SESSION.md is stale).
- SESSION.md = task state; auto memory = durable facts; this CLAUDE.md = standing rules; another repo → `pass`.
- Sessions you started report back by message or as `[Cairn] New notes`; tell me in one line each. Never ask me for screenshots: run `cairn.py shot` and Read the PNG.
- If sessions start heavy, run `context-audit` yourself.

## Compact instructions
When compacting, keep: current goal, decisions, files edited, failing tests/errors, next steps.
<!-- cairn:end -->
