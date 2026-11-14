# Cairn

Session manager for Claude Code (terminal + the desktop app's Code tab).

## Requirements
- Python 3.8 or newer (standard library only). Windows: `python` from python.org or the Store; macOS/Linux: `python3`.
- Claude Code (the CLI, or the desktop app's Code tab).
- Optional: `git` (only for `spawn --new-repo`) and the `claude` CLI logged in (`claude auth login`), only for
  terminal background/cloud sessions. Without them Cairn tells you and the Code tab's own session tool is used.

## Install on each computer
```
git clone https://github.com/LeventeDaniel/cairn
cd cairn/kit
python3 install.py        # Windows: python install.py
```
Then start a new session. It works for whichever Claude account is signed in on that computer.
Installing is safe to re-run. It edits `~/.claude/settings.json` (hooks, status line, permissions; a copy of the original
is kept as `settings.json.cairn-bak`) and adds a marked block to `~/.claude/CLAUDE.md` without touching your own text.
It never needs admin rights.
Remove: `python3 install.py --uninstall` (takes out its hooks, block, skills, agents and script; keeps `REPOS.md`,
`inbox/`, `SESSION.md` files and your `cairn/config.json`, `board.json`).
Tests: `python -m unittest discover -s tests`.

For the Code tab, also install the companion mod, which compacts at clean breaks and shows the
Cairn pane: `claude plugin install cairn@cairn`
(github.com/LeventeDaniel/cairn).

## Keep every computer in sync (recommended)
Put this folder in a private git repo, clone it to `~/.claude/cairn/kit-repo` on each computer,
and run `python3 install.py` from there. Updates: `git pull && python3 install.py`.

## What you do
Nothing, mostly. With the Cairn mod installed, context is compacted at clean breaks; without it,
type `/clear` when Cairn tells you. A weekly check for new Claude Code features and a weekly
tidy-up offer come once a week per computer.

Skills: `/handoff`, `/pass`, `/repos`, `/where-to-run`, `/context-audit`, `/skill-scout`, `/cairn-update`, `dispatch` (Home's routine).

## Cairn Home (one place to type new work)
Open a new Code-tab session in `~/.claude/cairn/home` and just say what you want. Home never does the work: it
picks the model and effort, writes a brief, starts a small worker session titled `<repo>: <task>`, and keeps a
board (`cairn.py board`, also in the mod's pane). Follow-ups go straight to the worker. Workers that stumble on a
new task send it to Home. At most `max_running` (3) workers run; the rest wait as queued.

## What it does
- **Routing**: every new instruction is checked; independent work goes to its own session. In the
  Code tab Claude uses the app's own session tools; in a terminal, `cairn.py spawn` starts
  `claude --bg` / `--cloud` sessions (it refuses, with the reason, when the CLI isn't logged in).
  Spawned sessions report back by message; cloud ones in their final message.
- **Session lifecycle**: each session is titled `<repo>: <task>`; finished ones get an Archive offer.
- **Context**: nudges before context fills up (deferring to the Cairn mod when it runs), and flags a
  message that looks like a new task when the context is already big.
- **Memory**: SESSION.md per repo reloads at start; notes for another repo go through `/pass`.

## Commands (`python ~/.claude/cairn/cairn.py <command>`)
| command | what it does |
|---|---|
| `workspace [--json]` | every repo in `~/.claude/REPOS.md`: goal, live sessions (`claude agents`), size, cache warm or cold, worktrees, notes waiting |
| `dispatch --repo R --title T [--kind small/normal/hard/design/cloud]` | Home: add a task to the board (cap check, model/effort defaults) |
| `report <id> [--session S] [--status …] [--note …]` | update a board row |
| `board [--json]` | the task board, statuses from `claude agents` |
| `cleanup [--json]` | stale worktrees (no commit for `stale_days`) and old closed sessions; reports only, removes nothing |
| `spawn --where bg/cloud --name N --task T [--repo P] [--new-repo PURPOSE] [--from-session S] [--dry-run]` | start a session elsewhere (`--dry-run` prints the command and prompt) |
| `audit` | what loads into every session, in tokens |
| `statusline`, `prompt`, `session-start`, `stop` | the hooks themselves (`stop` puts a worker's own last line on its board row) |

## Tuning (`~/.claude/cairn/config.json`)
`warn`, `urgent`, `tool_results`, `usage_warn`, `repeat_every`, `max_spawns_per_day` (6),
`repos_dir` (`~/Projects`), `prune_days` (30), `workspace_days` (14), `stale_days` (14),
`shift_pct` (30: topic-shift notes only from this % of context), `max_running` (3), `board_keep_days` (7). The mod's own keys
(`compact_mode`, `compact_soft`, …) live in the same file.

## Screenshots
`cairn.py shot` lets Claude look at your screen instead of asking you for screenshots (Windows: PowerShell; macOS: `screencapture`; Linux: `grim`, `gnome-screenshot`, `scrot` or ImageMagick `import`). The PNG is saved to `~/.claude/cairn/shots/latest.png` (local only, overwritten each time).

## Fewer approval prompts (opt-in)
`python3 install.py --routine-allow` also allows tests and local git bookkeeping without a prompt (unittest, pytest,
git status/diff/log/show/add/commit). It never allows push, install, delete or network commands. Re-run `install.py`
without the flag, or `--uninstall`, to remove exactly the rules it added; your own rules stay.
Cairn Home asks you once, up front, which risky steps a task may take and passes that to the worker as `Authorized:`.
What no setting can change: the app only takes an approval typed in the worker's own session, and its safety
classifier can still block risky actions.
