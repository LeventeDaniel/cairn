#!/usr/bin/env python3
"""Install, update or remove Cairn for Claude Code (all projects, this computer).

  python3 install.py              install or update (safe to re-run)
  python3 install.py --uninstall  remove it (keeps REPOS.md, inbox and SESSION.md files)

Works on macOS, Linux and Windows. Needs only Python 3.
"""
import json, os, re, shutil, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
HOME = Path.home() / ".claude"
CAIRN = HOME / "cairn"
SETTINGS = HOME / "settings.json"
CLAUDE_MD = HOME / "CLAUDE.md"
AGENTS = ["scout", "researcher", "architect", "Explore"]
SKILLS = ["handoff", "pass", "repos", "context-audit", "skill-scout", "cairn-update", "where-to-run", "dispatch"]
MARK = re.compile(r"\n?<!-- (?:context-coach|cairn):start -->.*?<!-- (?:context-coach|cairn):end -->\n?", re.S)
OLD = HOME / "coach"  # Cairn was called Context Coach until 2026-11-13
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


def save_settings(s):
    bak = SETTINGS.with_suffix(".json.cairn-bak")
    if SETTINGS.exists() and not bak.exists():
        shutil.copy2(SETTINGS, bak)
    SETTINGS.write_text(json.dumps(s, indent=2) + "\n", encoding="utf-8")


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
    shutil.copy2(HERE / "cairn.py", CAIRN / "cairn.py")
    (CAIRN / "home").mkdir(parents=True, exist_ok=True)  # Cairn Home: open a Code-tab session in this folder
    (CAIRN / "home" / "CLAUDE.md").write_text(
        (HERE / "home" / "CLAUDE.md").read_text(encoding="utf-8").replace("{{CAIRN}}", cmd("").strip()), encoding="utf-8")
    (HOME / "agents").mkdir(parents=True, exist_ok=True)
    for a in AGENTS:
        shutil.copy2(HERE / "agents" / f"{a}.md", HOME / "agents" / f"{a}.md")
    for sk in SKILLS:
        (HOME / "skills" / sk).mkdir(parents=True, exist_ok=True)
        shutil.copy2(HERE / "skills" / sk / "SKILL.md", HOME / "skills" / sk / "SKILL.md")
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
    old = s.get("statusLine")
    if old and not is_ours(old):
        cfg["chain_statusline"] = old.get("command")      # keep the user's status line and show both
        cfg["previous_statusline"] = old
    s["statusLine"] = {"type": "command", "command": cmd("statusline")}
    allow = s.setdefault("permissions", {}).setdefault("allow", [])
    allow[:] = [r for r in allow if not re.search(r"(cairn|coach)\.py (spawn|dispatch|report|board)", r)]
    allow.extend(f"Bash({cmd(c)}:*)" for c in ("spawn", "dispatch", "report", "board"))
    s.setdefault("env", {}).setdefault("CLAUDE_AUTOCOMPACT_PCT_OVERRIDE", AUTOCOMPACT)
    cfg["set_autocompact"] = s["env"]["CLAUDE_AUTOCOMPACT_PCT_OVERRIDE"] == AUTOCOMPACT
    save_settings(s)
    cfgp.write_text(json.dumps(cfg, indent=2), encoding="utf-8")

    md = CLAUDE_MD.read_text(encoding="utf-8") if CLAUDE_MD.exists() else ""
    md = MARK.sub("\n", md).rstrip()
    block = (HERE / "CLAUDE-block.md").read_text(encoding="utf-8").strip().replace("{{SPAWN}}", cmd("spawn"))
    CLAUDE_MD.write_text((md + "\n\n" if md else "") + block + "\n", encoding="utf-8")
    print("Cairn installed. Start a new Claude Code session (or restart the Code tab) to load it.")


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
        perms["allow"] = [r for r in perms["allow"] if not re.search(r"cairn\.py (spawn|dispatch|report|board)", r)]
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
