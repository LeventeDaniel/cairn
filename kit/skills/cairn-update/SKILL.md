---
name: cairn-update
description: Check for new Claude Code / Claude desktop features that affect Cairn and propose kit updates. Use when Cairn says a weekly check is due, or the user types /cairn-update.
---
1. Read `~/.claude/cairn/config.json` → `last_update_check` (date of the previous check; if missing, use 14 days ago).
2. Hand the research to the `researcher` subagent: what changed in Claude Code and the Claude desktop app's Code tab since that date. Sources: the official changelog (code.claude.com/docs/en/changelog), the Claude desktop changelog, reputable weekly roundups. No answers from memory.
3. Keep only changes that affect the kit: hooks, status line fields, compaction, auto memory, subagents/models/effort, skills, plugins/mods, worktrees/agent teams, Code-tab differences, anything that breaks or replaces a kit feature.
4. Report in under 15 lines: each change with its source link and the exact edit you propose to files in `~/.claude/cairn/`, `~/.claude/skills/`, `~/.claude/agents/` or the Cairn block in `~/.claude/CLAUDE.md`. If nothing relevant changed, say so in one line.
5. Apply only the edits the user approves. If `~/.claude/cairn/kit-repo` exists (a git checkout of the kit), make the same edits there and commit, so other computers get them with `git pull && python3 install.py`.
6. Set `last_update_check` in `~/.claude/cairn/config.json` to today.
