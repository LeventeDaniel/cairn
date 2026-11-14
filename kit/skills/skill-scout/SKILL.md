---
name: skill-scout
description: Turn a procedure the user keeps repeating into a reusable skill. Use when Cairn reports repeated procedures, or the user types /skill-scout.
---
1. Read `~/.claude/cairn/procedures.md` (lines: `- date | project | procedure`) and pick procedures done 3+ times that have no skill in `~/.claude/skills/`.
2. For the one the user picks, draft `~/.claude/skills/<kebab-name>/SKILL.md`: frontmatter `name` + a one-sentence `description` saying when to use it, then short numbered steps with exact commands. Under 40 lines.
3. Show the draft, save it on the user's OK, and say it's available from the next session.
