#!/usr/bin/env python3
"""Install, update or remove Cairn for Claude Code (all projects, this computer).

  python3 install.py              install or update (safe to re-run)
  python3 install.py --uninstall  remove it (keeps REPOS.md, inbox and SESSION.md files)

Works on macOS, Linux and Windows. Needs only Python 3.
"""
import json, os, re, shutil, sys, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
HOME = Path.home() / ".claude"
CAIRN = HOME / "cairn"
SETTINGS = HOME / "settings.json"
CLAUDE_MD = HOME / "CLAUDE.md"
AGENTS = ["scout", "researcher", "architect", "Explore"]
SKILLS = ["handoff", "pass", "repos", "context-audit", "skill-scout", "cairn-update", "where-to-run", "dispatch", "route"]
MARK = re.compile(r"\n?<!-- (?:context-coach|cairn):start -->.*?<!-- (?:context-coach|cairn):end -->\n?", re.S)
OLD = HOME / "coach"  # Cairn was called Context Coach until 2026-11-13
# Opt-in (`install.py --routine-allow`): checks and local git bookkeeping that never leave the machine or spend money.
# Never push, install, delete or network commands. Removed again by --uninstall or by re-running without the flag.
ROUTINE_ALLOW = ["Bash(python -m unittest:*)", "Bash(python3 -m unittest:*)", "Bash(python -m pytest:*)",
                 "Bash(python3 -m pytest:*)", "Bash(pytest:*)", "Bash(git status:*)", "Bash(git diff:*)",
                 "Bash(git log:*)", "Bash(git show:*)", "Bash(git add:*)", "Bash(git commit:*)"]
AUTOCOMPACT = "80"  # compact at 80% instead of the default (~97% on 1M models)


def q(p):
    p = Path(p).as_posix()
    return f'"{p}"' if " " in p else p


def cmd(sub):
    return f"{q(sys.executable)} {q(CAIRN / 'cairn.py')} {sub}"


def is_ours(h):
    c = h.get("command", "")
    return any(x in c for x in ("cairn.py", "coach.py", "context_coach.py", "reload_session.sh"))


def load_settings():
    if SETTINGS.exists():
        try:
            return json.loads(SETTINGS.read_text(encoding="utf-8"))
        except ValueError:
            sys.exit(f"{SETTINGS} isn't valid JSON — fix it first, nothing was changed.")
    return {}


def write_atomic(path, text):
    """Write next to the target, then swap it in: a session reading settings.json or running cairn.py
    mid-install must never see half a file."""
    tmp = path.with_name(path.name + ".cairn-tmp")
    tmp.write_text(text, encoding="utf-8")
    for i in range(8):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:  # Windows: a running hook has the old file open for a moment
            if i == 7:
                raise
            time.sleep(0.05 * (i + 1))


def save_settings(s):
    bak = SETTINGS.with_suffix(".json.cairn-bak")
    if SETTINGS.exists() and not bak.exists():
        shutil.copy2(SETTINGS, bak)
    write_atomic(SETTINGS, json.dumps(s, indent=2) + "\n")


def mod_behind():
    """A line to print when the Cairn mod (a plugin, which install.py does not manage) is older than this
    checkout's, else "". Without it a stale pane went unnoticed.
    A plugin from a marketplace added as a local folder is loaded in place from that folder at every session
    start and never copied (code.claude.com/docs/en/plugins/loading), so there the folder is what counts."""
    try:
        here = json.loads((HERE.parent / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))["version"]
        rows = json.loads((HOME / "plugins" / "installed_plugins.json").read_text(encoding="utf-8"))["plugins"]
        key = lambda v: [int(x) if x.isdigit() else 0 for x in str(v).split(".")]
        try:
            markets = json.loads((HOME / "plugins" / "known_marketplaces.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            markets = {}
        for pid, installs in rows.items():
            name, _, market = pid.partition("@")
            if name != "cairn" or not installs:
                continue
            src = (markets.get(market) or {}).get("source") or {}
            if src.get("source") in ("directory", "file") and src.get("path"):
                folder = Path(src["path"])
                if folder.resolve() == HERE.parent.resolve():
                    return ""
                have = json.loads((folder / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))["version"]
                if key(have) < key(here):
                    return (f"The Cairn mod (pane, compaction) is loaded in place from {folder}, which has {have}; this "
                            f"checkout has {here}. Bring that folder up to date (git pull there); new sessions pick it up.")
                return ""
            have = installs[0].get("version")
            if have and key(have) < key(here):
                return (f"The Cairn mod (pane, compaction) installed as a plugin is {have}; this checkout has {here}. "
                        f"Update it: claude plugin update {pid}")
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        pass
    return ""


def strip_hooks(s):
    hooks = s.get("hooks", {})
    for ev in list(hooks):
        groups = []
        for g in hooks[ev]:
            g = dict(g, hooks=[h for h in g.get("hooks", []) if not is_ours(h)])
            if g["hooks"]:
                groups.append(g)
        if groups:
            hooks[ev] = groups
        else:
            del hooks[ev]
    if not hooks:
        s.pop("hooks", None)


def migrate():
    """Context Coach -> Cairn: move ~/.claude/coach (state, config, logs) and drop the old script and skill."""
    if OLD.is_dir() and not CAIRN.exists():
        OLD.rename(CAIRN)
    for p in (CAIRN / "coach.py", HOME / "skills" / "coach-update" / "SKILL.md"):
        if p.exists():
            p.unlink()
    shutil.rmtree(HOME / "skills" / "coach-update", ignore_errors=True)
    shutil.rmtree(CAIRN / "__pycache__", ignore_errors=True)


def install():
    migrate()
    CAIRN.mkdir(parents=True, exist_ok=True)
    (HOME / "inbox").mkdir(parents=True, exist_ok=True)
    write_atomic(CAIRN / "cairn.py", (HERE / "cairn.py").read_text(encoding="utf-8"))
    shutil.copymode(HERE / "cairn.py", CAIRN / "cairn.py")
    (CAIRN / "home").mkdir(parents=True, exist_ok=True)  # Cairn Home: open a Code-tab session in this folder
    (CAIRN / "home" / "CLAUDE.md").write_text(
        (HERE / "home" / "CLAUDE.md").read_text(encoding="utf-8").replace("{{CAIRN}}", cmd("").strip()), encoding="utf-8")
    (HOME / "agents").mkdir(parents=True, exist_ok=True)
    for a in AGENTS:
        shutil.copy2(HERE / "agents" / f"{a}.md", HOME / "agents" / f"{a}.md")
    for sk in SKILLS:
        (HOME / "skills" / sk).mkdir(parents=True, exist_ok=True)
        text = (HERE / "skills" / sk / "SKILL.md").read_text(encoding="utf-8").replace("{{SPAWN}}", cmd("spawn"))
        (HOME / "skills" / sk / "SKILL.md").write_text(text, encoding="utf-8")
    reg = HOME / "REPOS.md"
    old_reg = HOME / "PROJECTS.md"
    if not reg.exists() and old_reg.exists() and "# Project registry" in old_reg.read_text(encoding="utf-8", errors="ignore"):
        old_reg.rename(reg)
    shutil.rmtree(HOME / "skills" / "projects", ignore_errors=True)  # renamed to "repos"
    if not reg.exists():
        reg.write_text("# Repo registry\n", encoding="utf-8")
    cfgp = CAIRN / "config.json"
    cfg = json.loads(cfgp.read_text(encoding="utf-8")) if cfgp.exists() else {}

    s = load_settings()
    strip_hooks(s)
    hooks = s.setdefault("hooks", {})
    hooks.setdefault("UserPromptSubmit", []).append({"hooks": [{"type": "command", "command": cmd("prompt")}]})
    hooks.setdefault("SessionStart", []).append({"hooks": [{"type": "command", "command": cmd("session-start")}]})
    # async: it only writes a board row, the turn must not wait for it
    hooks.setdefault("Stop", []).append({"hooks": [{"type": "command", "command": cmd("stop"), "async": True}]})
    # the turn ended on an API error (the usage limit, overload): the same command marks the board row "stopped"
    hooks.setdefault("StopFailure", []).append({"hooks": [{"type": "command", "command": cmd("stop"), "async": True}]})
    old = s.get("statusLine")
    if old and not is_ours(old):
        cfg["chain_statusline"] = old.get("command")      # keep the user's status line and show both
        cfg["previous_statusline"] = old
    s["statusLine"] = {"type": "command", "command": cmd("statusline")}
    allow = s.setdefault("permissions", {}).setdefault("allow", [])
    allow[:] = [r for r in allow if not re.search(r"(cairn|coach)\.py (spawn|dispatch|report|board|stats)", r)]
    allow.extend(f"Bash({cmd(c)}:*)" for c in ("spawn", "dispatch", "report", "board", "stats"))
    ours = set(cfg.get("routine_allow", []))          # rules a previous --routine-allow run added (not the user's own)
    allow[:] = [r for r in allow if r not in ours]
    cfg["routine_allow"] = []
    if "--routine-allow" in sys.argv:
        cfg["routine_allow"] = [r for r in ROUTINE_ALLOW if r not in allow]
        allow.extend(cfg["routine_allow"])
    s.setdefault("env", {}).setdefault("CLAUDE_AUTOCOMPACT_PCT_OVERRIDE", AUTOCOMPACT)
    cfg["set_autocompact"] = s["env"]["CLAUDE_AUTOCOMPACT_PCT_OVERRIDE"] == AUTOCOMPACT
    save_settings(s)
    cfgp.write_text(json.dumps(cfg, indent=2), encoding="utf-8")

    md = CLAUDE_MD.read_text(encoding="utf-8") if CLAUDE_MD.exists() else ""
    md = MARK.sub("\n", md).rstrip()
    block = (HERE / "CLAUDE-block.md").read_text(encoding="utf-8").strip().replace("{{SPAWN}}", cmd("spawn"))
    CLAUDE_MD.write_text((md + "\n\n" if md else "") + block + "\n", encoding="utf-8")
    print("Cairn installed. Start a new Claude Code session (or restart the Code tab) to load it.")
    behind = mod_behind()
    if behind:
        print(behind)


def uninstall():
    cfgp = CAIRN / "config.json"
    cfg = json.loads(cfgp.read_text(encoding="utf-8")) if cfgp.exists() else {}
    s = load_settings()
    strip_hooks(s)
    if "cairn.py" in (s.get("statusLine") or {}).get("command", ""):
        if cfg.get("previous_statusline"):
            s["statusLine"] = cfg["previous_statusline"]
        else:
            s.pop("statusLine", None)
    if cfg.get("set_autocompact") and s.get("env", {}).get("CLAUDE_AUTOCOMPACT_PCT_OVERRIDE") == AUTOCOMPACT:
        del s["env"]["CLAUDE_AUTOCOMPACT_PCT_OVERRIDE"]
        if not s["env"]:
            del s["env"]
    perms = s.get("permissions", {})
    if "allow" in perms:
        mine = set(cfg.get("routine_allow", []))
        perms["allow"] = [r for r in perms["allow"]
                          if not re.search(r"cairn\.py (spawn|dispatch|report|board|stats)", r) and r not in mine]
        if not perms["allow"]:
            del perms["allow"]
        if not perms:
            del s["permissions"]
    save_settings(s)
    if CLAUDE_MD.exists():
        CLAUDE_MD.write_text(MARK.sub("\n", CLAUDE_MD.read_text(encoding="utf-8")).strip() + "\n", encoding="utf-8")
    for a in AGENTS:
        (HOME / "agents" / f"{a}.md").unlink(missing_ok=True)
    for sk in SKILLS:
        shutil.rmtree(HOME / "skills" / sk, ignore_errors=True)
    for sub in ["state", "marks", "nag"]:
        shutil.rmtree(CAIRN / sub, ignore_errors=True)
    (CAIRN / "cairn.py").unlink(missing_ok=True)
    (CAIRN / "home" / "CLAUDE.md").unlink(missing_ok=True)
    print("Cairn removed. Kept: ~/.claude/REPOS.md, ~/.claude/inbox, ~/.claude/cairn/procedures.md, SESSION.md files.")


if __name__ == "__main__":
    if sys.version_info < (3, 8):
        sys.exit("Cairn needs Python 3.8 or newer (this is %d.%d)." % sys.version_info[:2])
    for _s in (sys.stdout, sys.stderr):  # Windows consoles default to cp1252 and garble the dashes
        try:
            _s.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    uninstall() if "--uninstall" in sys.argv else install()
