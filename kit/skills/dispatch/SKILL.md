---
name: dispatch
description: Cairn Home's routine for every request - classify it, pick where it runs and with which model/effort, write a self-contained brief, start the worker session and record it on Cairn's board. Use in the Cairn Home session for each new request, or when a worker sends Home a new task.
---
# Dispatch (Cairn Home)

`cairn.py …` below: run it with the full command from Home's CLAUDE.md (Commands). Never read code yourself; for facts you need to write the brief
(which repo, which files), one `scout` subagent call.

## 1. Classify
| the request is… | kind | where | model / effort |
|---|---|---|---|
| status, sessions, repos | — | answer from `cairn.py board` | — |
| find / read / summarise / "where is X" | — | `scout` subagent, relay its summary in a few lines | haiku |
| small, clear change (1-3 files, known fix) | small | worker session | Sonnet 5.5, low |
| normal feature or fix | normal | worker session | Sonnet 5.5, medium |
| bug with unknown cause, risky change | hard | worker session | Opus 5.5, high |
| design / architecture, then build | design | worker session in plan mode | Opus 5.5, high |
| long, unattended, repo on GitHub | cloud | cloud session (`target: "cloud"`) | Sonnet 5.5, medium |
| a stream of related cloud tasks | — | suggest a Claude Code Project in one line (name + first instruction) | — |
| several independent tasks | per row | one worker each, `use_worktree: true` when two touch the same repo | per row |

Unsure between two rows: the cheaper one. A follow-up on a task that already has a worker: tell the user to type it
there (link the session), don't start another.

## 1b. New project (no repo yet)
Run `cairn.py new-repo --name <kebab-name> --purpose "<one line>"` first (REFUSED = name taken: pick another). Then
continue below with `--repo <name>` and `cwd` = the path it printed. The app asks to trust the new folder once: tell
the user in one line to click Allow/Trust on that card. Don't ask anything else.

## 1c. Ask once, up front (approvals live in Home)
Workers can't take an approval relayed by Home, and the app may still prompt for installs, pushes or trusting a repo. So
before starting, decide which risky steps the task will plausibly need and ask the user ONE `AskUserQuestion`
(multiSelect, in Home, now): `install packages` / `push to the user's own remote` / `spend up to N USD` / `delete files` /
`trust a new folder`. Only list what the task really needs; skip the question when it needs none. Never offer force-push,
deleting data you can't restore, or anything outside the user's own repos. Put the answer in the brief (`Authorized:`)
and in `--scope`. The user's choice in this chat is a real instruction to the worker; the worker may act inside it
without asking again. Anything outside it, or any app dialog that still appears, the worker handles by batching (below).

## 2. Board first
`cairn.py dispatch --repo <name from REPOS.md> --title "<repo>: <task in 2-5 words>" --kind <kind> [--scope "<answers>"]`
- `OK t7 model=… effort=…` → go on.
- `QUEUED t7 …` → don't start it; tell the user in one line. Start it when a running one is done
  (`cairn.py report` prints `QUEUED TASK CAN START` when a slot frees).
- `ALREADY ON THE BOARD: t5 …` → that task has a worker; say so in one line with its link, start nothing.

## 3. The brief (the worker sees nothing of this chat)
```
Goal: <one sentence, what the user wants and why>
Repo: <path from REPOS.md>   Files/area: <paths or "find them">
Done when: <checkable: tests pass / committed / the user sees X>
Authorized by the user in Cairn Home chat on <date>: <the ticked steps, with limits> | none.
Constraints: <the user's rules that matter: no private names in public repos, don't push unless asked, ...>
Approvals: do all safe work first. Collect every step that still needs the user (outside Authorized, or an app
dialog you can't clear) and ask ONCE at the end of your turn, as a single list. Never push, spend or delete beyond Authorized.
Report: when done or blocked, end your turn with a one-line summary (it reaches Cairn Home automatically).
If a new, unrelated task comes up, send it to "Cairn Home" with SendMessage instead of doing it.
```

## 4. Start it
`mcp__ccd_session__start_session`: `initiation: "user_asked"`, `context: "fresh"`, `cwd: <repo path>`, `title`: the
board title, `prompt`: the brief, `background`: 2-3 sentences of context, `model` / `effort` from step 2
(model ids as the app's model picker lists them, e.g. `claude-sonnet-5-5`, `claude-opus-5-5`), `permission_mode:
"plan"` for kind design.

The app only starts a worker at or below Home's own model and effort. For Opus or high effort:
1. start it with `prompt: "Hold: reply only 'ready'. Your task follows in a message."` and no model/effort,
2. `mcp__ccd_session_mgmt__set_session_model` (opus id) and `set_session_effort` (high) on its session_id — the app
   asks the user to approve once,
3. send the brief with `SendMessage` (`to`: its `local_…` id).

## 5. Record and reply
`cairn.py report <t-id> --session <session_id from the result>`, then reply in 1-2 lines:
`Started [<title>](#local_<id>) on <model>/<effort>: <what it will do>.` Nothing else.
