---
name: context-audit
description: Find what wastes context in every session (CLAUDE.md, rules, auto memory, skills, agents, plugins, MCP servers) and trim it. Use when the user types /context-audit or asks why sessions start heavy.
---
1. Run `python3 ~/.claude/cairn/cairn.py audit --exact` (on Windows: `python`) from the project root. `--exact` adds Claude Code's own count per category (`/context`, run by the CLI: no model call, nothing to type).
2. Report the top 3 costs in one line each, with a concrete fix: move long CLAUDE.md procedures into skills or `.claude/rules/` with path scoping, shorten skill descriptions to 1-2 sentences, turn off plugins that are not used in Claude Code (each lists all its skills in every session; the audit names the heaviest) and unused MCP servers, prune stale auto-memory lines.
3. Apply only the fixes the user approves. Keep a backup copy (`<file>.bak`) of anything you edit.
