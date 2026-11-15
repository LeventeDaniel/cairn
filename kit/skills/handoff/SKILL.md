---
name: handoff
description: Save the current task state to SESSION.md so /clear or compaction loses nothing. Use when the user types /handoff, when Cairn says context is filling up, or before a long break.
---
Rewrite `SESSION.md` in the project root (replace, don't append). If this session was started by Cairn (its first message began with `[Started by Cairn`), write `SESSION-<session name>.md` instead so you never overwrite the parent session's state. Max ~40 lines:

## Goal — one line
## Decisions — still-relevant choices and why, one line each
## Done — finished pieces with file paths
## Next — numbered; step 1 concrete enough to start immediately
## Gotchas — things that bit us, commands, preferences stated in chat

What goes where:
- SESSION.md = this task's moving state (overwritten each time).
- Auto memory = durable facts about the project/user that outlive this task. Save those there, not here.
- CLAUDE.md = standing rules. If the user stated a new standing rule, propose adding it to CLAUDE.md.
- Something another project needs → use the pass skill.

Then say in one line: "Saved to SESSION.md." Nothing about /clear or compacting: that runs by itself, and the state reloads after it.
