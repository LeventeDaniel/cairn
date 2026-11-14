#!/usr/bin/env python3
"""Cairn v3 — one engine for Claude Code (terminal + desktop Code tab).

Subcommands (wired up by install.py):
  statusline     status line: shows context %, usage; saves exact numbers for the hooks
  prompt         UserPromptSubmit hook: advises /clear, handoff, subagents, model choice
  session-start  SessionStart hook: restores SESSION.md, delivers inbox notes, keeps repo registry
  audit          prints what loads into every session and how big it is
  spawn          lets Claude start a background/cloud session (or a new repo) on its own
  dispatch       Home: add a task to the board (checks the running cap, fills model/effort defaults)
  report         update a board row (session id, status, one-line report)
  board          the task board, statuses refreshed from `claude agents`
  workspace      every registered repo: goal, live sessions, worktrees, notes waiting (--json)
  cleanup        list stale worktrees and old closed sessions (removes nothing)
  shot           save a screenshot of the primary screen to ~/.claude/cairn/shots/latest.png

Only standard-library Python. Works on macOS, Linux and Windows.
"""
import json, os, re, shutil, subprocess, sys, time
from datetime import date
from pathlib import Path

HOME = Path.home() / ".claude"
CAIRN = HOME / "cairn"
REGISTRY = HOME / "REPOS.md"
INBOX = HOME / "inbox"
PROCS = CAIRN / "procedures.md"
CFG = CAIRN / "config.json"

DEFAULTS = {"warn": 50, "urgent": 70, "tool_results": 40, "usage_warn": 80,
            "repeat_every": 8, "max_spawns_per_day": 6, "repos_dir": "~/Projects",
            "prune_days": 30, "workspace_days": 14, "stale_days": 14, "shift_pct": 30,
            "max_running": 3, "board_keep_days": 7}
BOARD = CAIRN / "board.json"
HOME_DIR = CAIRN / "home"
HOME_TITLE = "Cairn Home"
# The dispatch table's defaults (PLAN-orchestrator.md); Home names the kind, Cairn fills model and effort.
KINDS = {"small": ("sonnet", "low"), "normal": ("sonnet", "medium"), "hard": ("opus", "high"),
         "design": ("opus", "high"), "cloud": ("sonnet", "medium")}


def cfg():
    c = dict(DEFAULTS)
    try:
        c.update(json.loads(CFG.read_text(encoding="utf-8")))
    except (OSError, ValueError):
        pass
    return c


def read_json(p, default=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def write_json(p, data):
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    os.replace(tmp, p)


def write_text_atomic(p, text):
    p = Path(p)
    tmp = p.with_name(p.name + f".{os.getpid()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, p)


def safe_id(s):
    return re.sub(r"[^A-Za-z0-9_-]", "", s or "")[:80] or "unknown"


# ---------------------------------------------------------------- status line
def cmd_statusline():
    try:
        d = json.load(sys.stdin)
    except ValueError:
        d = {}
    cw = d.get("context_window") or {}
    rl = d.get("rate_limits") or {}
    state = {
        "t": time.time(),
        "pct": cw.get("used_percentage"),
        "window": cw.get("context_window_size"),
        "five_hour": (rl.get("five_hour") or {}).get("used_percentage"),
        "seven_day": (rl.get("seven_day") or {}).get("used_percentage"),
        "model": (d.get("model") or {}).get("display_name"),
    }
    sid = safe_id(d.get("session_id"))
    write_json(CAIRN / "state" / f"{sid}.json", state)
    write_json(CAIRN / "state" / "last.json", state)

    c = cfg()
    pct = state["pct"]
    parts = [f"[{state['model'] or '?'}]"]
    if pct is not None:
        flag = " ⚠ clear soon" if pct >= c["urgent"] else (" ●" if pct >= c["warn"] else "")
        parts.append(f"{pct:.0f}% ctx{flag}")
    if state["five_hour"] is not None:
        parts.append(f"5h {state['five_hour']:.0f}%")
    if state["seven_day"] is not None:
        parts.append(f"7d {state['seven_day']:.0f}%")
    line = " · ".join(parts)

    prev = c.get("chain_statusline")  # the user's own status line, kept alongside ours
    if prev:
        try:
            out = subprocess.run(prev, shell=True, input=json.dumps(d), text=True,
                                 capture_output=True, timeout=5).stdout.strip()
            if out:
                line = out + " | " + line
        except (OSError, subprocess.SubprocessError):
            pass
    print(line)


# ---------------------------------------------------------------- transcript
def scan_transcript(path, start_line):
    """Return (tokens in context at the last assistant turn, tool results since last reset/compaction)."""
    used, tools, model = 0, 0, ""
    try:
        with open(path, encoding="utf-8") as f:
            for i, line in enumerate(f):
                if i < start_line:
                    continue
                try:
                    e = json.loads(line)
                except ValueError:
                    continue
                if e.get("type") == "system" and e.get("subtype") == "compact_boundary" or e.get("isCompactSummary"):
                    tools = 0
                    continue
                msg = e.get("message") or {}
                u = msg.get("usage") if isinstance(msg, dict) else None
                if e.get("type") == "assistant" and isinstance(msg, dict) and msg.get("model"):
                    model = msg["model"]
                if e.get("type") == "assistant" and u:
                    used = (u.get("input_tokens", 0) + u.get("cache_creation_input_tokens", 0)
                            + u.get("cache_read_input_tokens", 0))
                if e.get("type") == "user" and isinstance(msg.get("content"), list):
                    tools += sum(1 for c in msg["content"]
                                 if isinstance(c, dict) and c.get("type") == "tool_result")
    except OSError:
        pass
    return used, tools, model


def guess_window(model):
    """Claude Code runs current models (Fable, Opus 4.7+, Sonnet 5+, Haiku 5.5) with 1M context; older ones 200K."""
    m = (model or "").lower()
    if re.search(r"(haiku|sonnet|opus)-4-[0-6]\b|-3-|claude-3", m) or "haiku-4-5" in m:
        return 200000
    return 1000000


def line_count(path):
    try:
        with open(path, encoding="utf-8") as f:
            return sum(1 for _ in f)
    except OSError:
        return 0


# ---------------------------------------------------------------- prompt hook
STOP = set("""about after again also another because before being between could does doing done each from have
here into just like make more most much need only other over please same should some still such than that their
them then there these they this those through very want what when where which while will with would your yours
yeah okay sure thanks thank right also lets let's""".split())


def words(text):
    return {w for w in re.findall(r"[a-z][a-z0-9_-]{3,}", text.lower()) if w not in STOP}


def topic_shift(prompt, cwd):
    """The session's goal when a substantial new prompt shares no word with goal or next steps; else ''."""
    pw = words(prompt)
    if len(pw) < 6 or prompt.lstrip().startswith(("[", "<", "/")):
        return ""
    try:
        t = (Path(project_root(str(cwd))) / "SESSION.md").read_text(encoding="utf-8", errors="replace")
    except (OSError, TypeError):
        return ""
    goal = re.search(r"##\s*Goal[^\n]*\n+([^\n]+)", t)
    nxt = re.search(r"##\s*Next[^\n]*\n+([\s\S]{0,1500})", t)
    if not goal:
        return ""
    known = words(goal.group(1) + " " + (nxt.group(1) if nxt else ""))
    return goal.group(1).strip() if known and not (pw & known) else ""


def watcher_mode():
    """cairn's compact_mode (config.json, default smart)."""
    return (read_json(CFG, {}) or {}).get("compact_mode", "smart")


def cmd_prompt():
    try:
        d = json.load(sys.stdin)
    except ValueError:
        return
    c = cfg()
    sid = safe_id(d.get("session_id"))
    tpath = d.get("transcript_path", "")
    marks = read_json(CAIRN / "marks" / f"{sid}.json", {}) or {}
    used, tools, model = scan_transcript(tpath, marks.get("reset_line", 0))

    st = read_json(CAIRN / "state" / f"{sid}.json")
    if not st:
        last = read_json(CAIRN / "state" / "last.json")
        st = last if last and time.time() - last.get("t", 0) < 600 else {}
    window = st.get("window") or c.get("fallback_window") or guess_window(model)
    pct = st.get("pct")
    if pct is None and used:
        pct = 100 * used / window
    if pct is None:
        pct = 0

    level = 2 if pct >= c["urgent"] else (1 if pct >= c["warn"] else 0)
    notes = []
    # With the cairn mod compacting at clean breaks, "/clear" advice would contradict it.
    watcher = st.get("via") == "cairn" and watcher_mode() != "off"
    if watcher:
        if level == 2:
            notes.append(f"Context is {pct:.0f}% full. cairn compacts at the end of this turn with Cairn's notes; "
                         "if SESSION.md is stale, run the handoff skill first. No /clear needed.")
    elif level == 2:
        notes.append(f"Context is {pct:.0f}% full. Do this now, before the user's request: run the "
                     "handoff skill yourself to save state to SESSION.md, then tell the user in one line "
                     "to type /clear (their state will reload automatically).")
    elif level == 1:
        notes.append(f"Context is {pct:.0f}% full. At the next natural stopping point, run the handoff "
                     "skill yourself and suggest /clear in one line.")
    cwd = d.get("cwd") or os.getcwd()
    home = is_home(cwd)
    shift = "" if home else topic_shift(d.get("prompt") or "", Path(cwd))
    worker = bool(shift) and is_worker(sid)
    if worker:
        notes.append(f"This message looks like a new task (no overlap with your goal: '{shift[:80]}'). You are a worker "
                     f"started by {HOME_TITLE}: don't do it here. Find '{HOME_TITLE}' with ListAgents and send it the "
                     "task with SendMessage (one self-contained paragraph: what, which repo, why it came up), then tell "
                     f"the user in one line that {HOME_TITLE} will start it. Only if the user says to do it here, do it.")
    elif shift and pct >= c["shift_pct"]:
        notes.append(f"This message looks like a new task (no overlap with this session's goal: '{shift[:80]}'), "
                     f"and context is {pct:.0f}% full. Route it per the Routing rules; if it belongs here, compact or "
                     "hand off first so the old task's context doesn't ride along.")
    if tools >= c["tool_results"]:
        notes.append(f"{tools} tool results are in context since the last reset. Send further searching, "
                     "file/log reading or research to the scout or researcher subagent.")
    fh, sd = st.get("five_hour"), st.get("seven_day")
    if (fh or 0) >= c["usage_warn"] or (sd or 0) >= c["usage_warn"]:
        notes.append(f"Plan usage is high (5h {fh or 0:.0f}%, 7d {sd or 0:.0f}%). Prefer haiku/sonnet "
                     "subagents and low effort; suggest a smaller main model with /model in one line.")

    # Don't nag: speak when something changes, then every N prompts while it persists.
    nag = read_json(CAIRN / "nag" / f"{sid}.json", {}) or {}
    key = f"{level}|{tools >= c['tool_results']}|{bool(notes and 'usage' in notes[-1])}|{bool(shift)}"
    since = nag.get("since", 0) + 1
    speak = notes and (key != nag.get("key") or since >= c["repeat_every"])
    write_json(CAIRN / "nag" / f"{sid}.json", {"key": key, "since": 0 if speak else since})
    inbox_note = take_inbox(marks.get("repo"))
    if not marks.get("named") and os.environ.get("CLAUDE_CODE_ENTRYPOINT") == "claude-desktop":
        marks["named"] = True
        write_json(CAIRN / "marks" / f"{sid}.json", marks)
        repo = marks.get("repo") or "this repo"
        if home:
            print(f"[Cairn] Title this session '{HOME_TITLE}' with the app's session-title tool, silently. "
                  "Workers find Home by that title.")
        else:
            print(f"[Cairn] Once this session's task is clear, title it '{repo}: <task in 2-5 words>' with "
                  "the app's session-title tool, silently (no need to tell the user). Skip it if it already has such a title.")
    if speak:
        print("[Cairn] " + " ".join(notes))
    if inbox_note:
        print(inbox_note)


def take_inbox(name):
    """Return new notes for this repo (and archive them), or ''."""
    if not name:
        return ""
    box = INBOX / f"{name}.md"
    try:
        notes = box.read_text(encoding="utf-8")
    except OSError:
        return ""
    if not notes.strip():
        return ""
    arch = INBOX / "archive"
    arch.mkdir(parents=True, exist_ok=True)
    with open(arch / f"{name}.md", "a", encoding="utf-8") as a:
        a.write(notes)
    box.write_text("", encoding="utf-8")
    return (f"[Cairn] New notes for '{name}' (results from sessions you started, or notes from other "
            "repos) — tell the user in one line each:\n" + notes[:3000])


# ---------------------------------------------------------------- projects
def project_root(cwd):
    """Main repo root, so every git worktree of a repo maps to one project."""
    try:
        common = subprocess.run(["git", "-C", cwd, "rev-parse", "--path-format=absolute", "--git-common-dir"],
                                capture_output=True, text=True, timeout=5).stdout.strip()
        if common:
            p = Path(common)
            return str(p.parent if p.name == ".git" else p)
    except (OSError, subprocess.SubprocessError):
        pass
    return str(Path(cwd).resolve())


def git_exclude(cwd):
    """Keep SESSION*.md out of commits (uses .git/info/exclude, so nothing in the repo changes)."""
    try:
        gd = subprocess.run(["git", "-C", cwd, "rev-parse", "--path-format=absolute", "--git-common-dir"],
                            capture_output=True, text=True, timeout=5).stdout.strip()
        if not gd:
            return
        ex = Path(gd) / "info" / "exclude"
        cur = ex.read_text(encoding="utf-8") if ex.exists() else ""
        if "SESSION*.md" not in cur:
            ex.parent.mkdir(parents=True, exist_ok=True)
            ex.write_text(cur.rstrip("\n") + ("\n" if cur else "") + "# Cairn\nSESSION*.md\n", encoding="utf-8")
    except (OSError, subprocess.SubprocessError):
        pass


def norm(p):
    return os.path.normcase(os.path.normpath(p))


def registry_touch(root):
    """Find (or auto-add) the project for root and stamp today's date. Returns (name, was_new)."""
    REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    lines = REGISTRY.read_text(encoding="utf-8").splitlines() if REGISTRY.exists() else ["# Repo registry"]
    today = date.today().isoformat()
    best = None
    for i, ln in enumerate(lines):
        f = [x.strip() for x in ln.lstrip("- ").split("|")]
        if not ln.startswith("-") or len(f) < 5:
            continue
        p = norm(f[1])
        r = norm(root)
        if r == p:
            best = (i, len(p), f)
            break
    if best:
        i, _, f = best
        f[4] = today
        lines[i] = "- " + " | ".join(f)
        write_text_atomic(REGISTRY, "\n".join(lines) + "\n")
        return f[0], False
    name = re.sub(r"[^A-Za-z0-9_.-]", "-", Path(root).name) or "project"
    taken = {ln.lstrip("- ").split("|")[0].strip() for ln in lines if ln.startswith("-")}
    base, n = name, 2
    while name in taken:
        name, n = f"{base}-{n}", n + 1
    lines.append(f"- {name} | {root} | ? | active | {today}")
    write_text_atomic(REGISTRY, "\n".join(lines) + "\n")
    return name, True


def repeated_procedures(min_count=3):
    if not PROCS.exists():
        return []
    counts = {}
    for ln in PROCS.read_text(encoding="utf-8").splitlines():
        f = [x.strip() for x in ln.lstrip("- ").split("|")]
        if len(f) >= 3 and f[2]:
            k = f[2].lower()
            counts[k] = counts.get(k, 0) + 1
    have = {p.name.lower() for p in (HOME / "skills").glob("*")} if (HOME / "skills").exists() else set()
    return [k for k, v in counts.items() if v >= min_count and re.sub(r"\W+", "-", k) not in have]


def router_context(name, sess):
    goal = "not set yet"
    if sess.exists():
        m = re.search(r"##\s*Goal[^\n]*\n+([^\n#]+)", sess.read_text(encoding="utf-8", errors="replace"))
        if m:
            goal = m.group(1).strip()[:200]
    others = []
    if REGISTRY.exists():
        for ln in REGISTRY.read_text(encoding="utf-8").splitlines():
            f = [x.strip() for x in ln.lstrip("- ").split("|")]
            if ln.startswith("-") and len(f) >= 5 and f[0] != name and f[3] != "done":
                others.append(f"{f[0]} ({f[2]})")
    return (f"[Cairn · Router] This session: repo '{name}', goal: {goal}. "
            f"Other repos: {', '.join(others[:15]) or 'none'}. "
            "Route every new instruction using the 'Routing' rules in CLAUDE.md.")


def cmd_session_start():
    try:
        d = json.load(sys.stdin)
    except ValueError:
        d = {}
    sid = safe_id(d.get("session_id"))
    source = d.get("source", "startup")
    # Compaction/clear: count tool results only from here on.
    reset_line = line_count(d.get("transcript_path", ""))
    write_json(CAIRN / "nag" / f"{sid}.json", {})

    cwd = d.get("cwd") or os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    out = []
    sess = Path(os.environ.get("CLAUDE_PROJECT_DIR") or cwd) / "SESSION.md"
    if sess.exists():
        out.append("[Cairn] Saved working state from SESSION.md is below. If the user's first message "
                   "starts with '[Started by Cairn', IGNORE it (it belongs to another session). If the user's "
                   "next instruction is unrelated, treat that as the new goal. Otherwise continue from here:\n"
                   + sess.read_text(encoding="utf-8", errors="replace")[:5000])

    if is_home(cwd):
        write_json(CAIRN / "marks" / f"{sid}.json", {"reset_line": reset_line, "repo": "home", "home": True})
        rows = [t for t in board_rows(refresh=False) if t["status"] in ("running", "waiting", "queued")]
        board = "; ".join(f"{t['id']} {t['status']} '{t['title']}'" for t in rows[:12]) or "empty"
        print(f"[Cairn · Home] You are {HOME_TITLE}: route, never do the work (rules in this folder's CLAUDE.md, "
              f"dispatch skill for every request). Board: {board}. Repos: "
              + ", ".join(f"{r['name']} ({r['purpose']})" for r in registry()[:15]))
        return
    root = project_root(cwd)
    git_exclude(cwd)
    name, new = registry_touch(root)
    if new:
        out.append(f"[Cairn] New repo '{name}' added to ~/.claude/REPOS.md. Ask the user, in "
                   "one line, for a one-line purpose and fill it in (replace the '?').")
    out.append(router_context(name, sess))
    write_json(CAIRN / "marks" / f"{sid}.json", {"reset_line": reset_line, "repo": name})
    note = take_inbox(name)
    if note:
        out.append(note)

    if source == "startup":
        prune_state()
        c0 = read_json(CFG, {}) or {}
        last_clean = c0.get("cleanup_nudged") or "2000-01-01"
        if (date.today() - date.fromisoformat(last_clean[:10])).days >= 7:
            rows = stale()
            c0["cleanup_nudged"] = date.today().isoformat()
            write_json(CFG, c0)
            if rows:
                nw = sum(len(r["worktrees"]) for r in rows)
                ns = sum(r["oldSessions"] for r in rows)
                out.append(f"[Cairn] Weekly tidy-up: {nw} stale worktree(s), {ns} old closed session(s) across "
                           f"{len(rows)} repo(s). After the user's first request, offer in one line to tidy up: run "
                           "`cairn.py cleanup` and follow its Next line.")
        reps = repeated_procedures()
        if reps:
            out.append("[Cairn] Procedures done 3+ times with no skill yet: " + ", ".join(reps[:5])
                       + ". Offer, in one line, to turn one into a skill (skill-scout skill).")
    if source == "startup":
        c = read_json(CFG, {}) or {}
        # the later of the last real check (cairn-update) and the last nudge
        last = max(c.get("last_update_check") or "2000-01-01", c.get("update_nudged") or "2000-01-01")
        if (date.today() - date.fromisoformat(last[:10])).days >= 7:
            c["update_nudged"] = date.today().isoformat()  # nudge once a week per computer
            write_json(CFG, c)
            out.append("[Cairn] Weekly feature check is due. After the user's first request is handled, "
                       "offer in one line to run the cairn-update skill (it uses the researcher subagent).")
    if out:
        print("\n\n".join(out)[:9500])  # hook output is cut at 10,000 characters


# ---------------------------------------------------------------- audit
def tok(text):
    return len(text) // 4


def cmd_audit():
    cwd = Path(os.getcwd())
    rows = []

    def add(label, path):
        p = Path(path)
        if p.is_file():
            t = p.read_text(encoding="utf-8", errors="replace")
            rows.append((tok(t), label, f"{len(t.splitlines())} lines", str(p)))

    add("User CLAUDE.md", HOME / "CLAUDE.md")
    for cand in [cwd / "CLAUDE.md", cwd / ".claude" / "CLAUDE.md", cwd / "CLAUDE.local.md"]:
        add("Project CLAUDE.md", cand)
    for r in sorted((cwd / ".claude" / "rules").glob("*.md")) if (cwd / ".claude" / "rules").exists() else []:
        add("Project rule", r)
    for mem in (HOME / "projects").glob("*/memory/MEMORY.md") if (HOME / "projects").exists() else []:
        t = mem.read_text(encoding="utf-8", errors="replace")
        loaded = "\n".join(t.splitlines()[:200])
        rows.append((tok(loaded), "Auto memory (first 200 lines load)", f"{len(t.splitlines())} lines", str(mem)))

    skills = []
    for root in [HOME / "skills", cwd / ".claude" / "skills"]:
        for s in root.glob("*/SKILL.md") if root.exists() else []:
            head = s.read_text(encoding="utf-8", errors="replace").split("---")
            desc = head[1] if len(head) > 2 else ""
            skills.append((tok(desc), s.parent.name))
    agents = []
    for root in [HOME / "agents", cwd / ".claude" / "agents"]:
        for a in root.glob("*.md") if root.exists() else []:
            head = a.read_text(encoding="utf-8", errors="replace").split("---")
            agents.append((tok(head[1] if len(head) > 2 else ""), a.stem))

    settings = read_json(HOME / "settings.json", {}) or {}
    plugins = [k for k, v in (settings.get("enabledPlugins") or {}).items() if v]
    mcp = list(((read_json(Path.home() / ".claude.json", {}) or {}).get("mcpServers") or {}).keys())

    print("Loads into EVERY session (approx tokens):")
    for t, label, extra, path in sorted(rows, reverse=True):
        print(f"  {t:>6}  {label:<38} {extra:<12} {path}")
    print(f"  {sum(t for t, _ in skills):>6}  Skill descriptions ({len(skills)} skills)")
    for t, n in sorted(skills, reverse=True)[:5]:
        print(f"          {t:>4}  {n}")
    print(f"  {sum(t for t, _ in agents):>6}  Agent descriptions ({len(agents)} agents)")
    print(f"\nEnabled plugins ({len(plugins)}): {', '.join(plugins) or 'none'}")
    print(f"User MCP servers ({len(mcp)}): {', '.join(mcp) or 'none'}  (each adds tool definitions; run /context for exact numbers)")
    flags = [f"{label} is {extra}: aim for under ~200 lines" for t, label, extra, _ in rows
             if "CLAUDE.md" in label and int(extra.split()[0]) > 200]
    flags += [f"Skill '{n}' description is ~{t} tokens: tighten to one or two sentences" for t, n in skills if t > 120]
    if flags:
        print("\nFlags:\n  - " + "\n  - ".join(flags))


# ---------------------------------------------------------------- spawn (Claude starts sessions itself)
def claude_exe():
    """The claude CLI: on PATH, or the one running this hook (the desktop app keeps it off PATH)."""
    exe = shutil.which("claude") or os.environ.get("CLAUDE_CODE_EXECPATH") or ""
    if exe:
        return exe
    # Subprocesses of a mod have neither: fall back to the newest CLI the desktop app bundles.
    local = os.environ.get("LOCALAPPDATA")
    if local:
        found = sorted(Path(local).glob("Claude-Data/*/claude-code/*/*/claude.exe"),
                       key=lambda p: p.stat().st_mtime, reverse=True)
        if found:
            return str(found[0])
    return ""


def prune_state():
    """Per-session files (state/, marks/, nag/) older than prune_days go; they pile up otherwise."""
    cutoff = time.time() - cfg()["prune_days"] * 86400
    keep = {"last.json", "compact-decision.json", "workspace.json"}
    for d in ("state", "marks", "nag"):
        if not (CAIRN / d).is_dir():
            continue
        for f in (CAIRN / d).glob("*.json"):
            try:
                if f.name not in keep and f.stat().st_mtime < cutoff:
                    f.unlink()
            except OSError:
                pass


def cache_ttl_min():
    """Main-conversation prompt cache TTL: the promptCacheTtl setting, else 60 (subscription default)."""
    s = read_json(HOME / "settings.json", {}) or {}
    v = os.environ.get("CLAUDE_CODE_PROMPT_CACHE_TTL") or s.get("promptCacheTtl")
    return 5 if v == "5m" else 60


def registry():
    out = []
    try:
        for line in REGISTRY.read_text(encoding="utf-8").splitlines():
            parts = [x.strip() for x in line[2:].split("|")]
            if line.startswith("- ") and len(parts) >= 3:
                out.append({"name": parts[0], "path": parts[1], "purpose": parts[2]})
    except OSError:
        pass
    return out


def transcript_info(f, max_bytes=262144):
    """Title and context size from a transcript's tail (the format is internal: read little, trust less)."""
    title = tokens = None
    try:
        size = f.stat().st_size
        with open(f, "rb") as h:
            h.seek(max(0, size - max_bytes))
            lines = h.read().decode("utf-8", "replace").splitlines()
    except OSError:
        return None, None
    for line in reversed(lines):
        if title is None and '"custom-title"' in line:
            try:
                title = json.loads(line).get("customTitle")
            except ValueError:
                pass
        if tokens is None and '"usage"' in line and '"assistant"' in line:
            try:
                u = json.loads(line)["message"]["usage"]
                tokens = (u.get("input_tokens", 0) + u.get("cache_read_input_tokens", 0)
                          + u.get("cache_creation_input_tokens", 0))
            except (ValueError, KeyError, TypeError):
                pass
        if title is not None and tokens is not None:
            break
    return title, tokens


_AGENTS = None


def live_agents():
    """Live and background sessions from `claude agents --json --all` (the documented interface); once per run."""
    global _AGENTS
    if _AGENTS is not None:
        return _AGENTS
    exe = claude_exe()
    _AGENTS = []
    if exe:
        try:
            r = subprocess.run([exe, "agents", "--json", "--all"], capture_output=True, text=True,
                               timeout=20, encoding="utf-8", errors="replace")
            _AGENTS = json.loads(r.stdout) if r.returncode == 0 else []
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
    return _AGENTS


def is_home(cwd):
    try:
        return norm(str(Path(cwd).resolve())) == norm(str(HOME_DIR.resolve()))
    except (OSError, TypeError):
        return False


def is_worker(sid):
    """A session Home started (its row on the board names it)."""
    b = read_json(BOARD, {}) or {}
    return any(sid and sid in (t.get("cliSession"), (t.get("session") or "").replace("local_", ""))
               for t in b.get("tasks", []) if t.get("status") not in ("done", "closed"))


def workspace():
    """Every registered repo: goal, recent sessions (live state, size, cache warm/cold), notes waiting."""
    c = cfg()
    ttl = cache_ttl_min()
    now = time.time()
    agents = live_agents()
    by_sid = {a.get("sessionId"): a for a in agents}
    pdir = HOME / "projects"
    projects = [d for d in pdir.iterdir() if d.is_dir()] if pdir.is_dir() else []
    repos, claimed = [], set()
    for r in registry():
        enc = re.sub(r"[^A-Za-z0-9]", "-", r["path"]).lower()
        dirs = [d for d in projects if d.name.lower() == enc or d.name.lower().startswith(enc + "--claude-worktrees")]
        files = []
        for d in dirs:
            for f in d.glob("*.jsonl"):
                try:
                    m = f.stat().st_mtime
                except OSError:
                    continue
                if now - m < c["workspace_days"] * 86400:
                    files.append((m, f))
        files.sort(key=lambda x: -x[0])
        sessions = []
        for m, f in files[:5]:
            title, tokens = transcript_info(f)
            a = by_sid.get(f.stem) or {}
            age = (now - m) / 60
            sessions.append({"id": f.stem, "title": a.get("name") or title or f.stem[:8],
                             "status": a.get("status") or "closed", "kind": a.get("kind"),
                             "ageMin": round(age), "tokens": tokens, "warm": age < ttl})
            claimed.add(f.stem)
        rp = Path(r["path"])
        goal = nxt = ""
        try:
            t = (rp / "SESSION.md").read_text(encoding="utf-8", errors="replace")
            g = re.search(r"##\s*Goal[^\n]*\n+([^\n]+)", t)
            n = re.search(r"##\s*Next[^\n]*\n+([^\n]+)", t)
            goal = g.group(1).strip() if g else ""
            nxt = n.group(1).strip() if n else ""
        except OSError:
            pass
        inbox = HOME / "inbox" / f"{r['name']}.md"
        notes = 0
        if inbox.is_file():
            notes = len([l for l in inbox.read_text(encoding="utf-8", errors="replace").splitlines() if l.strip()])
        wt = rp / ".claude" / "worktrees"
        repos.append({"name": r["name"], "path": r["path"], "purpose": r["purpose"], "goal": goal, "next": nxt,
                      "sessions": sessions, "notes": notes,
                      "worktrees": len([d for d in wt.iterdir() if d.is_dir()]) if wt.is_dir() else 0})
    others = [{"title": a.get("name") or (a.get("sessionId") or "")[:8], "cwd": a.get("cwd"),
               "status": a.get("status"), "kind": a.get("kind")}
              for a in agents if a.get("sessionId") not in claimed
              and a.get("status") in ("busy", "idle", "waiting")]
    return {"at": now, "cacheTtlMin": ttl, "repos": repos, "unregistered": others}


def git_out(args, cwd):
    try:
        return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=20,
                              encoding="utf-8", errors="replace").stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def stale():
    """Worktrees and closed sessions nobody touched for stale_days, per registered repo."""
    c = cfg()
    now = time.time()
    cut = c["stale_days"] * 86400
    live = {a.get("sessionId") for a in live_agents() if a.get("status") in ("busy", "idle", "waiting")}
    pdir = HOME / "projects"
    projects = [d for d in pdir.iterdir() if d.is_dir()] if pdir.is_dir() else []
    out = []
    for r in registry():
        rp = Path(r["path"])
        wts = []
        wt = rp / ".claude" / "worktrees"
        for d in (sorted(wt.iterdir()) if wt.is_dir() else []):
            if not d.is_dir():
                continue
            last = git_out(["log", "-1", "--format=%ct"], d)
            age = now - (int(last) if last.isdigit() else d.stat().st_mtime)
            if age > cut:
                wts.append({"path": str(d), "branch": git_out(["branch", "--show-current"], d),
                            "dirty": bool(git_out(["status", "--porcelain"], d)), "ageDays": round(age / 86400)})
        enc = re.sub(r"[^A-Za-z0-9]", "-", r["path"]).lower()
        old = 0
        for d in projects:
            if d.name.lower() == enc or d.name.lower().startswith(enc + "--claude-worktrees"):
                for f in d.glob("*.jsonl"):
                    try:
                        if now - f.stat().st_mtime > cut and f.stem not in live:
                            old += 1
                    except OSError:
                        pass
        if wts or old:
            out.append({"name": r["name"], "worktrees": wts, "oldSessions": old})
    return out


def stale_cached(max_age=3600):
    """stale() runs git per worktree, so the workspace view reuses a result up to an hour old."""
    f = CAIRN / "state" / "stale.json"
    c = read_json(f, None)
    if isinstance(c, dict) and time.time() - c.get("at", 0) < max_age and isinstance(c.get("rows"), list):
        return c["rows"]
    rows = stale()
    write_json(f, {"at": time.time(), "rows": rows})
    return rows


def cmd_cleanup():
    """Report only: nothing is removed here. Claude asks the user before removing anything."""
    rows = stale()
    if "--json" in sys.argv:
        print(json.dumps(rows, ensure_ascii=False))
        return
    if not rows:
        print("Nothing stale.")
        return
    days = cfg()["stale_days"]
    for r in rows:
        print(f"{r['name']}:")
        for w in r["worktrees"]:
            print(f"  worktree {w['path']}  branch {w['branch'] or '?'}  {w['ageDays']} d old"
                  + ("  UNCOMMITTED CHANGES" if w["dirty"] else ""))
        if r["oldSessions"]:
            print(f"  {r['oldSessions']} closed session(s) untouched for {days}+ days")
    print("\nNext: show the user this list in a few lines and ask before removing anything. A clean worktree goes with "
          "`git worktree remove <path>` (then delete its branch if merged); one with uncommitted changes needs the "
          "user's decision. Old desktop sessions: archive them with the app's session tools (list, then archive), "
          "with the user's OK. Transcripts themselves expire by Claude Code's cleanupPeriodDays.")


# ---------------------------------------------------------------- board (Cairn Home's task list)
def board_load():
    b = read_json(BOARD, {}) or {}
    b.setdefault("tasks", [])
    b.setdefault("next", 1)
    return b


def board_find(b, key):
    key = (key or "").strip()
    for t in b["tasks"]:
        if key and key in (t["id"], t.get("session")):
            return t
    return None


def board_refresh(b, agents=None):
    """Live status from `claude agents`: busy → running, idle/waiting → waiting (on you); gone → closed.
    A desktop session's local_ id isn't the CLI session id, so match by id, else by title."""
    agents = live_agents() if agents is None else agents
    if not agents:
        return b  # no CLI or no answer: keep what we have rather than mark everything closed
    for t in b["tasks"]:
        if t["status"] in ("done", "queued"):
            continue
        sid = (t.get("session") or "").replace("local_", "")
        a = next((x for x in agents if sid and x.get("sessionId") == sid), None)
        if a is None:
            same = [x for x in agents if (x.get("name") or "").strip().lower() == t["title"].strip().lower()
                    and (x.get("startedAt") or 0) / 1000 >= t["started"] - 120]
            a = max(same, key=lambda x: x.get("startedAt") or 0) if same else None
        if a is None:
            if t["status"] != "closed" and time.time() - t["started"] > 300:
                t["status"] = "closed"
            continue
        t["cliSession"] = a.get("sessionId")
        st = a.get("status")
        t["status"] = "running" if st == "busy" else "waiting" if st in ("idle", "waiting") else t["status"]
    return b


def board_save(b):
    keep = time.time() - cfg()["board_keep_days"] * 86400
    b["tasks"] = [t for t in b["tasks"] if t["status"] not in ("done", "closed") or t.get("updated", t["started"]) > keep]
    write_json(BOARD, b)


def cmd_dispatch():
    import argparse
    ap = argparse.ArgumentParser(prog="cairn.py dispatch")
    ap.add_argument("--repo", required=True)
    ap.add_argument("--title", required=True, help="'<repo>: <task>'")
    ap.add_argument("--kind", choices=sorted(KINDS), default="normal")
    ap.add_argument("--model", default="")
    ap.add_argument("--effort", default="")
    ap.add_argument("--session", default="")
    ap.add_argument("--scope", default="", help="risky steps the user pre-approved in Home, e.g. 'install; spend<=5USD'")
    a = ap.parse_args(sys.argv[2:])
    c = cfg()
    b = board_refresh(board_load())
    model, effort = KINDS[a.kind]
    t = {"id": f"t{b['next']}", "repo": a.repo, "title": a.title[:80], "kind": a.kind,
         "model": a.model or model, "effort": a.effort or effort, "session": a.session,
         "status": "running", "started": time.time(), "updated": time.time(), "report": ""}
    if a.scope:
        t["scope"] = a.scope[:200]
    running = [x for x in b["tasks"] if x["status"] == "running"]
    if len(running) >= c["max_running"] and a.kind != "cloud":
        t["status"] = "queued"
    b["next"] += 1
    b["tasks"].append(t)
    board_save(b)
    if t["status"] == "queued":
        print(f"QUEUED {t['id']}: {len(running)} workers already running (cap {c['max_running']}). Do NOT start it now; "
              f"tell the user in one line it's queued behind: " + "; ".join(x['title'] for x in running) +
              f". Start it when one finishes, then `cairn.py report {t['id']} --status running --session <id>`.")
    else:
        print(f"OK {t['id']} model={t['model']} effort={t['effort']}" + (f" scope={t['scope']!r}" if a.scope else "") + f". Start the worker now, titled '{t['title']}', "
              f"then record it: `cairn.py report {t['id']} --session <the session_id start_session returned>`.")


def cmd_report():
    import argparse
    ap = argparse.ArgumentParser(prog="cairn.py report")
    ap.add_argument("key", help="task id (t3) or session id")
    ap.add_argument("--status", choices=["running", "waiting", "done", "queued", "closed"])
    ap.add_argument("--session", default="")
    ap.add_argument("--note", default="", help="one-line report")
    a = ap.parse_args(sys.argv[2:])
    b = board_load()
    t = board_find(b, a.key)
    if not t:
        sys.exit(f"No board task '{a.key}'. `cairn.py board` lists them.")
    if a.session:
        t["session"] = a.session
    if a.status:
        t["status"] = a.status
    if a.note:
        t["report"] = a.note.replace("\n", " ")[:200]
    t["updated"] = time.time()
    board_save(b)
    print(f"{t['id']} {t['status']}: {t['title']}" + (f" — {t['report']}" if t["report"] else ""))


def board_rows(refresh=True):
    b = board_load()
    if refresh and any(t["status"] in ("running", "waiting") for t in b["tasks"]):
        b = board_refresh(b)
        board_save(b)
    order = {"waiting": 0, "running": 1, "queued": 2, "done": 3, "closed": 4}
    return sorted(b["tasks"], key=lambda t: (order.get(t["status"], 5), -t["started"]))


def cmd_board():
    rows = board_rows()
    if "--json" in sys.argv:
        print(json.dumps(rows, ensure_ascii=False))
        return
    if not rows:
        print("Board is empty.")
        return
    mark = {"running": "●", "waiting": "!", "queued": "…", "done": "✓", "closed": "○"}
    for t in rows:
        age = round((time.time() - t["started"]) / 60)
        print(f"{mark.get(t['status'], '?')} {t['id']:4} {t['status']:7} {t['title'][:50]:50} {t['model']}/{t['effort']}"
              f"  {age} min" + (f"\n         {t['report']}" if t.get("report") else ""))


def cmd_workspace():
    w = workspace()
    w["board"] = board_rows()
    w["stale"] = stale_cached()
    write_json(CAIRN / "state" / "workspace.json", w)
    if "--json" in sys.argv:
        print(json.dumps(w, ensure_ascii=False))
        return

    def k(n):
        return "?" if n is None else f"{round(n / 1000)}k"

    def ago(m):
        return f"{m} min" if m < 120 else f"{round(m / 60)} h" if m < 2880 else f"{round(m / 1440)} d"

    for r in w["repos"]:
        print(f"{r['name']}  ({r['purpose']})" + (f"  · {r['notes']} note(s) waiting" if r["notes"] else "")
              + (f"  · {r['worktrees']} worktree(s)" if r["worktrees"] else ""))
        print(f"  goal: {r['goal'][:90] or '-'}")
        for s in r["sessions"]:
            live = "●" if s["status"] in ("busy", "idle", "waiting") else "○"
            print(f"  {live} {s['title'][:48]:48} {s['status']:7} {ago(s['ageMin']):>6} ago "
                  f"{k(s['tokens']):>5}  cache {'warm' if s['warm'] else 'cold'}")
    for o in w["unregistered"]:
        print(f"(not in REPOS.md) {o['title'][:48]}  {o['status']}  {o['cwd']}")


def cli_logged_in(exe):
    """`claude auth status` says loggedIn; unknown (old CLI, error) counts as logged in."""
    try:
        r = subprocess.run([exe, "auth", "status"], capture_output=True, text=True, timeout=20,
                           encoding="utf-8", errors="replace")
        return json.loads(r.stdout).get("loggedIn", True) is not False
    except (OSError, ValueError, AttributeError, subprocess.SubprocessError):
        return True


def cloud_streak(log, from_session, days=7):
    """Cloud sessions started for the same goal in the last `days` days (spawned.md)."""
    since = date.fromordinal(date.today().toordinal() - days).isoformat()
    want = from_session[:80].replace("|", "/").strip()
    n = 0
    for ln in log.read_text(encoding="utf-8").splitlines() if log.exists() else []:
        parts = [x.strip() for x in ln[2:].split("|")]
        if len(parts) >= 6 and parts[0] >= since and parts[1] == "cloud" and parts[5] == want:
            n += 1
    return n


def create_repo(name, purpose, c=None):
    """New project folder under repos_dir: git init, README, starter CLAUDE.md + SESSION.md, one commit,
    REPOS.md line with the real purpose. Returns (path, error)."""
    c = c or cfg()
    purpose = " ".join(purpose.replace("|", "/").split()) or "?"
    repo = Path(os.path.expanduser(c["repos_dir"])) / name
    if repo.exists() and any(repo.iterdir()):
        return None, f"REFUSED: {repo} already exists and isn't empty. Pick another name or use --repo."
    if any(r["name"] == name for r in registry()):
        return None, f"REFUSED: '{name}' is already in REPOS.md. Pick another name."
    if not shutil.which("git"):
        return None, "REFUSED: git isn't installed (or not on PATH), so a new repo can't be created. Install git first."
    repo.mkdir(parents=True, exist_ok=True)
    (repo / "README.md").write_text(f"# {name}\n\n{purpose}\n", encoding="utf-8")
    (repo / "CLAUDE.md").write_text(f"# {name}\n\nPurpose: {purpose}\n\nNo build or test commands yet; add them here once they exist.\n", encoding="utf-8")
    (repo / "SESSION.md").write_text(f"# Session state\n\nGoal: {purpose}\nStatus: just created, nothing built yet.\n", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=repo)
    subprocess.run(["git", "add", "-A"], cwd=repo)
    subprocess.run(["git", "-c", "user.name=Cairn", "-c", "user.email=cairn@localhost", "commit", "-q", "-m", "Initial commit"], cwd=repo)
    lines = REGISTRY.read_text(encoding="utf-8").splitlines() if REGISTRY.exists() else ["# Repo registry"]
    lines.append(f"- {name} | {repo} | {purpose} | active | {date.today().isoformat()}")
    REGISTRY.parent.mkdir(parents=True, exist_ok=True)
    write_text_atomic(REGISTRY, "\n".join(lines) + "\n")
    return repo, None


def cmd_new_repo():
    """Create the folder + registry line only (Home then starts the worker with the app's session tool)."""
    import argparse
    ap = argparse.ArgumentParser(prog="cairn.py new-repo")
    ap.add_argument("--name", required=True)
    ap.add_argument("--purpose", required=True)
    a = ap.parse_args(sys.argv[2:])
    name = re.sub(r"[^A-Za-z0-9_.-]", "-", a.name).strip("-") or "project"
    repo, err = create_repo(name, a.purpose)
    if err:
        print(err)
        return
    print(f"CREATED {name} at {repo} (git init + first commit, registered in REPOS.md). Next: `cairn.py dispatch --repo {name} "
          f"--title \"{name}: <first task>\" --kind <kind>`, then start_session with cwd {repo}. The app asks the user to "
          f"trust this new folder once: tell them in one line to click Allow/Trust on that card, nothing else.")


def cmd_spawn():
    import argparse, shutil
    ap = argparse.ArgumentParser(prog="cairn.py spawn")
    ap.add_argument("--where", choices=["bg", "cloud"], default="bg")
    ap.add_argument("--name", required=True)
    ap.add_argument("--task", required=True)
    ap.add_argument("--repo", help="folder to run in (default: current folder)")
    ap.add_argument("--new-repo", metavar="PURPOSE", help="create a new repo folder named --name with this purpose")
    ap.add_argument("--from-session", default="", help="name/goal of the session that started this")
    ap.add_argument("--dry-run", action="store_true", help="print the command and prompt, start nothing")
    a = ap.parse_args(sys.argv[2:])
    c = cfg()
    name = re.sub(r"[^A-Za-z0-9_.-]", "-", a.name).strip("-") or "task"

    # daily cap so it can't run away with your usage
    log = CAIRN / "spawned.md"
    today = date.today().isoformat()
    n_today = sum(1 for ln in log.read_text(encoding="utf-8").splitlines() if ln.startswith(f"- {today}")) if log.exists() else 0
    if n_today >= c["max_spawns_per_day"]:
        print(f"REFUSED: already started {n_today} sessions today (max_spawns_per_day in ~/.claude/cairn/config.json). Ask the user.")
        return

    if a.new_repo:
        if a.dry_run:
            repo = Path(os.path.expanduser(c["repos_dir"])) / name
        else:
            repo, err = create_repo(name, a.new_repo, c)
            if err:
                print(err)
                return
    else:
        repo = Path(os.path.expanduser(a.repo)) if a.repo else Path(os.getcwd())
        if not repo.is_dir():
            print(f"REFUSED: {repo} is not a folder.")
            return

    exe = claude_exe()
    if not exe:
        print("CANNOT START: the `claude` command isn't installed on this computer's PATH. Tell the user to "
              "open a new session in the Code tab instead (in folder " + str(repo) + "), with this first message:\n" + a.task)
        return
    if not cli_logged_in(exe):
        # The desktop app signs in on its own; the CLI it ships is not logged in, so a --bg/--cloud
        # session it starts would sit at "Not logged in". Seen live 2026-11-13.
        print("CANNOT START: the claude CLI on this computer isn't logged in (the desktop app signs in separately). "
              "In the Code tab, start the session with the app's own session tool instead (folder " + str(repo) +
              ", name it '<repo>: <task>'), with this first message:\n" + a.task +
              "\nIf the user wants terminal background sessions too, they can run `claude auth login` once in a terminal.")
        return

    inbox_name = (re.sub(r"[^A-Za-z0-9_.-]", "", a.from_session.split(":")[0].split()[0])
                  if a.from_session.strip() else "") or "results"
    parent_sid = os.environ.get("CLAUDE_CODE_SESSION_ID", "")
    parent = next((x for x in live_agents() if x.get("sessionId") == parent_sid), {}) if parent_sid else {}
    if a.where == "cloud":
        # A cloud session can't reach this machine: no ~/.claude, and it can't message local sessions back.
        report = ("When done, end with a one-line result as your final message (and in the PR description if you "
                  "open one); the session that started you reads it from claude.ai/code.")
    elif parent:
        report = (f"When done, report back in one line to the session that started you: run ListAgents, find the "
                  f"session named \"{parent.get('name')}\" (session id {parent_sid}), and SendMessage it the result. "
                  f"If it isn't listed or the send fails, append the line to ~/.claude/inbox/{inbox_name}.md instead.")
    else:
        report = f"When done, append a one-line result to ~/.claude/inbox/{inbox_name}.md so the original session hears about it."
    prompt = (f"[Started by Cairn{' from ' + a.from_session if a.from_session else ''}]\n{a.task}\n\n" + report)
    if a.where == "cloud":
        remote = subprocess.run(["git", "remote"], cwd=repo, capture_output=True, text=True).stdout.strip()
        if not remote:
            print("REFUSED: cloud sessions need the repo on GitHub, and this one has no git remote. Use --where bg instead.")
            return
        st_out = subprocess.run(["git", "status", "--porcelain", "-b"], cwd=repo, capture_output=True, text=True).stdout
        st_lines = st_out.splitlines()
        branch_line = st_lines[0] if st_lines else ""
        no_upstream = branch_line.startswith("## ") and "..." not in branch_line
        if "[ahead" in branch_line or no_upstream or len(st_lines) > 1:
            print("WARNING: this repo has uncommitted or unpushed changes; the cloud session only sees what's on GitHub. "
                  "Push first (with the user's OK) or use --where bg.")
            return
        cmdline = [exe, "--cloud", prompt]
    else:
        cmdline = [exe, "--bg", "--name", name, prompt]
    if a.dry_run:
        print("DRY RUN, nothing started:\n" + " ".join(cmdline[:-1]) + "\n---\n" + cmdline[-1])
        return
    try:
        r = subprocess.run(cmdline, cwd=repo, capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError) as ex:
        print(f"FAILED to start the session: {ex}. Tell the user and offer to do the task here instead.")
        return
    if r.returncode != 0:
        print("FAILED to start the session:\n" + ((r.stderr or r.stdout or "").strip()[:1500]) +
              "\nTell the user in one line and offer to do the task here instead.")
        return
    CAIRN.mkdir(parents=True, exist_ok=True)
    with open(log, "a", encoding="utf-8") as f:
        f.write(f"- {today} | {a.where} | {name} | {repo} | {a.task[:80].replace('|', '/')} | {a.from_session[:80].replace('|', '/')}\n")
    print((r.stdout or "").strip() or (r.stderr or "").strip() or "started")
    how = ("it reports back by message" if parent and a.where == "bg" else
           "its result is its final message at claude.ai/code" if a.where == "cloud" else
           "its result lands in the inbox on your next message")
    print(f"STARTED {a.where} session '{name}' in {repo} ({how}). Tell the user in one line where to find it "
          f"({'Code tab sidebar / claude.ai/code' if a.where == 'cloud' else 'Code tab sidebar or `claude agents`'}).")
    if a.where == "cloud" and a.from_session.strip():
        n = cloud_streak(log, a.from_session)
        if n >= 3:
            print(f"SUGGEST: {n} cloud sessions for '{a.from_session[:60]}' this week. Suggest, in one line, a Claude Code "
                  "Project (claude.ai/code, Projects) for this stream: give it a name and its first instruction. "
                  "One coordinator then runs the threads and shows which wait for review.")


def cmd_shot():
    """Capture the primary screen to ~/.claude/cairn/shots/latest.png and print the path.
    Windows: PowerShell. macOS: screencapture. Linux: grim, gnome-screenshot, scrot or ImageMagick import."""
    out = CAIRN / "shots" / "latest.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    if sys.platform == "win32":
        ps = ("Add-Type -AssemblyName System.Windows.Forms,System.Drawing;"
              "$b=[System.Windows.Forms.Screen]::PrimaryScreen.Bounds;"
              "$bmp=New-Object System.Drawing.Bitmap $b.Width,$b.Height;"
              "$g=[System.Drawing.Graphics]::FromImage($bmp);"
              "$g.CopyFromScreen($b.Location,[System.Drawing.Point]::Empty,$b.Size);"
              "$bmp.Save($env:CAIRN_SHOT,[System.Drawing.Imaging.ImageFormat]::Png);"
              "$g.Dispose();$bmp.Dispose()")
        argv = ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps]
    elif sys.platform == "darwin":
        argv = ["screencapture", "-x", str(out)]
    else:
        tools = [("grim", ["grim", str(out)]), ("gnome-screenshot", ["gnome-screenshot", "-f", str(out)]),
                 ("scrot", ["scrot", "-o", str(out)]), ("import", ["import", "-window", "root", str(out)])]
        argv = next((a for t, a in tools if shutil.which(t)), None)
        if not argv:
            print("SHOT FAILED: no screenshot tool found. Install one of: grim, gnome-screenshot, scrot, imagemagick.")
            return
    if not shutil.which(argv[0]):
        print(f"SHOT FAILED: `{argv[0]}` not found on PATH.")
        return
    out.unlink(missing_ok=True)
    r = subprocess.run(argv, env={**os.environ, "CAIRN_SHOT": str(out)}, capture_output=True, text=True)
    if r.returncode or not out.exists():
        print("SHOT FAILED: " + (r.stderr or r.stdout).strip()[:300]); return
    print(out)


if __name__ == "__main__":
    # Windows pipes default to cp1252, which can't print ● ⚠ · and crashed the status line.
    for _s in (sys.stdout, sys.stderr):
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd and cmd not in ("statusline", "prompt", "session-start", "audit", "spawn", "workspace", "shot",
                           "cleanup", "dispatch", "report", "board", "new-repo"):
        print(f"Unknown command '{cmd}'.\n"); print(__doc__); sys.exit(2)
    {"statusline": cmd_statusline, "prompt": cmd_prompt,
     "session-start": cmd_session_start, "audit": cmd_audit, "spawn": cmd_spawn, "new-repo": cmd_new_repo,
     "workspace": cmd_workspace, "shot": cmd_shot, "cleanup": cmd_cleanup,
     "dispatch": cmd_dispatch, "report": cmd_report, "board": cmd_board}.get(cmd, lambda: print(__doc__))()
