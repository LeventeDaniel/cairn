"""Checks for cairn.py dispatch / report / board and the Home/worker hooks. Run: python -m unittest tests/test_board.py"""
import importlib.util, io, json, os, re, subprocess, sys, tempfile, time, unittest
from contextlib import redirect_stdout
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("cairn", HERE / "cairn.py")


def load(tmp):
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    os.environ.pop("CLAUDE_PROJECT_DIR", None)  # set when the tests run inside a Claude session
    m.HOME = tmp
    m.CAIRN = tmp / "cairn"
    m.BOARD = m.CAIRN / "board.json"
    m.CFG = m.CAIRN / "config.json"
    m.HOME_DIR = m.CAIRN / "home"
    m.REGISTRY = tmp / "REPOS.md"
    m._AGENTS = []
    return m


def run(m, *argv, stdin=None):
    sys.argv = ["cairn.py", *argv]
    out = io.StringIO()
    old = sys.stdin
    if stdin is not None:
        sys.stdin = io.StringIO(json.dumps(stdin))
    try:
        with redirect_stdout(out):
            {"dispatch": m.cmd_dispatch, "stop": m.cmd_stop, "report": m.cmd_report, "board": m.cmd_board,
             "prompt": m.cmd_prompt, "new-repo": m.cmd_new_repo, "session-start": m.cmd_session_start,
             "spawn": m.cmd_spawn}[argv[0]]()
    finally:
        sys.stdin = old
    return out.getvalue()


class NewRepo(unittest.TestCase):
    def test_creates_folder_commit_and_registry(self):
        import subprocess
        tmp = Path(tempfile.mkdtemp())
        m = load(tmp)
        m.CAIRN.mkdir(parents=True)
        m.CFG.write_text(json.dumps({"repos_dir": str(tmp / "ws")}))
        out = run(m, "new-repo", "--name", "demo x", "--purpose", "does | Y")
        self.assertIn("CREATED demo-x", out)
        self.assertIn("trust", out)
        repo = tmp / "ws" / "demo-x"
        for f in ("README.md", "CLAUDE.md", "SESSION.md", ".git"):
            self.assertTrue((repo / f).exists(), f)
        log = subprocess.run(["git", "log", "--oneline"], cwd=repo, capture_output=True, text=True).stdout
        self.assertEqual(len(log.splitlines()), 1)
        self.assertEqual(m.registry()[0]["purpose"], "does / Y")
        self.assertIn("REFUSED", run(m, "new-repo", "--name", "demo-x", "--purpose", "again"))


class Board(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.m = load(self.tmp)

    def test_dispatch_fills_defaults_and_report_updates(self):
        out = run(self.m, "dispatch", "--repo", "example-a", "--title", "example-a: fix login", "--kind", "hard")
        self.assertIn("OK t1 model=opus effort=high", out)
        run(self.m, "report", "t1", "--session", "local_abc", "--note", "started")
        out = run(self.m, "report", "local_abc", "--status", "done", "--note", "fixed, committed")
        self.assertIn("t1 done", out)
        rows = json.loads(run(self.m, "board", "--json"))
        self.assertEqual(rows[0]["report"], "fixed, committed")
        self.assertEqual(rows[0]["session"], "local_abc")

    def test_cap_queues_the_fourth(self):
        for i in range(3):
            run(self.m, "dispatch", "--repo", "example-a", "--title", f"example-a: task {i}")
        out = run(self.m, "dispatch", "--repo", "example-b", "--title", "example-b: task 4")
        self.assertIn("QUEUED t4", out)
        out = run(self.m, "dispatch", "--repo", "example-b", "--title", "example-b: cloud", "--kind", "cloud")
        self.assertIn("OK t5", out)

    def test_refresh_matches_by_title_and_maps_status(self):
        run(self.m, "dispatch", "--repo", "example-a", "--title", "example-a: fix login", "--session", "local_x")
        run(self.m, "dispatch", "--repo", "example-b", "--title", "example-b: gone")
        b = json.loads(self.m.BOARD.read_text())
        b["tasks"][1]["started"] -= 600
        self.m.BOARD.write_text(json.dumps(b))
        self.m._AGENTS = [{"sessionId": "u1", "name": "example-a: fix login", "status": "idle",
                           "startedAt": time.time() * 1000}]
        self.m.GONE_GRACE = 0
        rows = {r["id"]: r for r in json.loads(run(self.m, "board", "--json"))}
        self.assertEqual(rows["t1"]["status"], "waiting")
        self.assertEqual(rows["t1"]["cliSession"], "u1")
        self.assertEqual(rows["t2"]["status"], "closed")

    def test_explicit_close_is_not_reopened_by_refresh(self):
        run(self.m, "dispatch", "--repo", "example-a", "--title", "example-a: done thing", "--session", "local_c1")
        run(self.m, "report", "t1", "--status", "closed")
        self.m._AGENTS = [{"sessionId": "c1", "name": "example-a: done thing", "status": "idle",
                           "startedAt": time.time() * 1000}]
        self.assertEqual(json.loads(run(self.m, "board", "--json"))[0]["status"], "closed")

    def test_note_from_before_idle_is_marked_stale(self):
        run(self.m, "dispatch", "--repo", "example-a", "--title", "example-a: long", "--session", "local_s1")
        run(self.m, "report", "t1", "--note", "still running")
        b = json.loads(self.m.BOARD.read_text())
        b["tasks"][0]["updated"] -= 60
        self.m.BOARD.write_text(json.dumps(b))
        self.m._AGENTS = [{"sessionId": "s1", "name": "example-a: long", "status": "idle",
                           "startedAt": time.time() * 1000}]
        row = json.loads(run(self.m, "board", "--json"))[0]
        self.assertEqual(row["status"], "waiting")
        self.assertTrue(row["reportStale"])
        run(self.m, "report", "t1", "--note", "finished, PR open")
        self.assertFalse(json.loads(run(self.m, "board", "--json"))[0]["reportStale"])

    def test_no_cli_answer_keeps_statuses(self):
        run(self.m, "dispatch", "--repo", "example-a", "--title", "example-a: x")
        self.m._AGENTS = []
        self.assertEqual(json.loads(run(self.m, "board", "--json"))[0]["status"], "running")

    def test_unknown_task_exits(self):
        with self.assertRaises(SystemExit):
            run(self.m, "report", "t99", "--status", "done")


class Hooks(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.m = load(self.tmp)
        self.repo = self.tmp / "example-a"
        self.repo.mkdir()
        (self.repo / "SESSION.md").write_text("## Goal\nShip the invoice exporter\n\n## Next\n- csv columns\n")

    def prompt(self, sid, cwd, text):
        return run(self.m, "prompt", stdin={"session_id": sid, "cwd": str(cwd), "prompt": text, "transcript_path": ""})

    def test_worker_topic_shift_goes_to_home(self):
        run(self.m, "dispatch", "--repo", "example-a", "--title", "example-a: invoices", "--session", "local_w1")
        out = self.prompt("w1", self.repo, "also please redesign the marketing website header banner colours today")
        self.assertIn("SendMessage", out)
        self.assertIn("Cairn Home", out)

    def test_worker_in_a_worktree_is_not_judged_by_the_main_checkouts_goal(self):
        git = lambda *a, cwd: subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *a],
                                             cwd=cwd, capture_output=True, text=True)
        git("init", "-q", cwd=self.repo)
        git("commit", "-q", "--allow-empty", "-m", "init", cwd=self.repo)
        wt = self.tmp / "wt"
        if git("worktree", "add", "-q", str(wt), cwd=self.repo).returncode:
            self.skipTest("git worktree not available")
        run(self.m, "dispatch", "--repo", "example-a", "--title", "example-a: banner", "--session", "local_w2")
        text = "also please redesign the marketing website header banner colours today"
        self.assertNotIn("new task", self.prompt("w2", wt, text))  # no SESSION.md of its own: nothing to compare
        (wt / "SESSION.md").write_text("## Goal\nRedesign the marketing website banner\n")
        self.assertNotIn("new task", self.prompt("w2", wt, text))
        self.assertIn("SendMessage", self.prompt("w2", wt, "now go and rewrite the payroll importer with proper retries everywhere"))

    def test_worktree_session_reads_its_own_session_file_when_the_project_dir_is_the_main_checkout(self):
        git = lambda *a, cwd: subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid", *a],
                                             cwd=cwd, capture_output=True, text=True)
        git("init", "-q", cwd=self.repo)
        git("commit", "-q", "--allow-empty", "-m", "init", cwd=self.repo)
        wt = self.tmp / "wt2"
        if git("worktree", "add", "-q", str(wt), cwd=self.repo).returncode:
            self.skipTest("git worktree not available")
        (wt / "SESSION.md").write_text("## Goal\nRedesign the marketing website banner\n")
        (wt / "src").mkdir()
        os.environ["CLAUDE_PROJECT_DIR"] = str(self.repo)  # what the desktop app gives a worktree session
        try:
            out = run(self.m, "session-start", stdin={"session_id": "w3", "cwd": str(wt), "source": "compact"})
            self.assertIn("Redesign the marketing website banner", out)
            self.assertNotIn("goal: not set yet", out)
            self.assertEqual(self.m.session_file(str(wt / "src")), wt.resolve() / "SESSION.md")
            # a session working inside its own project folder keeps that folder's file
            sub = self.repo / "pkg"
            sub.mkdir()
            self.assertEqual(self.m.session_file(str(sub)), self.repo / "SESSION.md")
            os.environ["CLAUDE_PROJECT_DIR"] = str(sub)
            self.assertEqual(self.m.session_file(str(sub)), sub / "SESSION.md")
        finally:
            os.environ.pop("CLAUDE_PROJECT_DIR", None)

    def test_plan_usage_from_before_the_reset_is_not_reported(self):
        st = self.m.CAIRN / "state" / "u1.json"
        st.parent.mkdir(parents=True)
        base = {"t": time.time(), "pct": 5, "five_hour": 91, "seven_day": 20}
        st.write_text(json.dumps({**base, "five_hour_resets": time.time() - 60}))
        self.assertNotIn("Plan usage", self.prompt("u1", self.repo, "carry on"))
        st.write_text(json.dumps({**base, "five_hour_resets": time.time() + 600}))
        (self.m.CAIRN / "nag" / "u1.json").unlink()
        self.assertIn("Plan usage is high", self.prompt("u1", self.repo, "carry on"))
        st.write_text(json.dumps({**base, "t": time.time() - 6 * 3600}))  # the mod's state: no reset time, hours old
        (self.m.CAIRN / "nag" / "u1.json").unlink()
        self.assertNotIn("Plan usage", self.prompt("u1", self.repo, "carry on"))

    def test_non_worker_low_context_says_nothing_about_home(self):
        out = self.prompt("other", self.repo, "also please redesign the marketing website header banner colours today")
        self.assertNotIn("Cairn Home", out)

    def test_restored_goal_is_not_repeated_in_the_router_line(self):
        out = run(self.m, "session-start", stdin={"session_id": "r1", "cwd": str(self.repo), "source": "resume"})
        self.assertEqual(out.count("Ship the invoice exporter"), 1)
        self.assertIn("goal: in SESSION.md above", out)

    def test_unknown_purpose_is_filled_in_by_claude_once_a_week(self):
        self.m.REGISTRY.write_text(f"# Repo registry\n- example-a | {self.repo} | ? | active | 2026-01-01\n")
        start = lambda: run(self.m, "session-start", stdin={"session_id": "r2", "cwd": str(self.repo), "source": "startup"})
        self.assertIn("still has '?' as the purpose of 'example-a'", start())
        self.assertNotIn("still has '?'", start())  # not again this week
        self.m.REGISTRY.write_text(f"# Repo registry\n- example-a | {self.repo} | invoices | active | 2026-01-01\n")
        self.m.CFG.write_text("{}")
        self.assertNotIn("still has '?'", start())  # a purpose is there: nothing to ask

    def test_home_session_start_skips_registry(self):
        self.m.HOME_DIR.mkdir(parents=True)
        out = run(self.m, "session-start", stdin={"session_id": "h", "cwd": str(self.m.HOME_DIR), "source": "startup"})
        self.assertIn("Cairn · Home", out)
        self.assertFalse(self.m.REGISTRY.exists() and "home" in self.m.REGISTRY.read_text())

    def test_scratch_folders_are_not_registered(self):
        import tempfile as tf
        scratch = Path(tf.mkdtemp(prefix="scratch-"))
        (scratch / ".git").mkdir()  # even a git folder under the temp dir is scratch
        out = run(self.m, "session-start", stdin={"session_id": "s1", "cwd": str(scratch), "source": "startup"})
        self.assertNotIn("New repo", out)
        self.assertFalse(self.m.REGISTRY.exists() and scratch.name in self.m.REGISTRY.read_text())


class Sturdy(unittest.TestCase):
    """Broken input or damaged state files: a hook never fails the user's turn, and the crash is on record."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.m = load(self.tmp)
        self.m.CAIRN.mkdir(parents=True)

    def hook(self, cmd, raw):
        old, sys.stdin = sys.stdin, io.StringIO(raw)
        out = io.StringIO()
        try:
            with redirect_stdout(out):
                self.m.run_command(cmd)
        finally:
            sys.stdin = old
        return out.getvalue()

    def test_a_config_value_of_the_wrong_kind_keeps_the_default(self):
        self.m.CFG.write_text(json.dumps({"repeat_every": "often", "usage_warn": True, "warn": 35.5,
                                          "repos_dir": 7, "my_own_key": "x"}))
        c = self.m.cfg()
        self.assertEqual((c["repeat_every"], c["usage_warn"], c["warn"]), (8, 80, 35.5))
        self.assertEqual((c["repos_dir"], c["my_own_key"]), ("~/Projects", "x"))
        self.m.CFG.write_text("[1, 2]")
        self.assertEqual(self.m.cfg(), self.m.DEFAULTS)

    def test_a_crashing_hook_exits_quietly_and_the_board_reports_it(self):
        for cmd in ("prompt", "session-start", "stop"):
            self.assertEqual(self.hook(cmd, "[]"), "")          # not a JSON object: used to be a traceback
        self.assertIn("status line error", self.hook("statusline", '"x"'))
        n, last = self.m.hook_errors()
        self.assertEqual(n, 4)
        self.assertIn("statusline: AttributeError", last)
        self.assertIn("Traceback", (self.m.CAIRN / "errors.log").read_text(encoding="utf-8"))
        self.assertIn("HOOK ERRORS: 4 Cairn hook crash(es)", run(self.m, "board"))
        self.m.HOME_DIR.mkdir(parents=True)
        self.assertIn("HOOK ERRORS", run(self.m, "session-start", stdin={"session_id": "h", "cwd": str(self.m.HOME_DIR)}))
        # yesterday's crashes are not news
        log = self.m.CAIRN / "errors.log"
        log.write_text(re.sub(r"^@ \d+", f"@ {int(time.time()) - 2 * 86400}", log.read_text(encoding="utf-8"), flags=re.M),
                       encoding="utf-8")
        self.assertEqual(self.m.hook_errors(), (0, ""))
        self.assertNotIn("HOOK ERRORS", run(self.m, "board"))

    def test_a_command_the_user_runs_still_shows_its_error(self):
        def boom():
            raise RuntimeError("boom")
        self.m.cmd_board = boom
        with self.assertRaises(RuntimeError):
            self.m.run_command("board")
        self.assertFalse((self.m.CAIRN / "errors.log").exists())

    def test_one_damaged_board_row_does_not_take_the_board_down(self):
        run(self.m, "dispatch", "--repo", "a", "--title", "a: job", "--session", "local_j")
        b = json.loads(self.m.BOARD.read_text(encoding="utf-8"))
        b["tasks"] += ["x", {"id": "t7"}, {"id": "t9", "status": "running", "started": "soon", "title": None}]
        del b["next"]
        self.m.BOARD.write_text(json.dumps(b))
        out = run(self.m, "board")
        self.assertIn("a: job", out)
        self.assertEqual([t["id"] for t in self.m.board_load()["tasks"]], ["t1", "t9"])
        self.assertEqual(self.m.board_load()["next"], 10)
        self.m.HOME_DIR.mkdir(parents=True)
        self.assertIn("Cairn Home", run(self.m, "session-start", stdin={"session_id": "h", "cwd": str(self.m.HOME_DIR)}))
        self.m.BOARD.write_text("[]")
        self.assertEqual(run(self.m, "board").strip(), "Board is empty.")


class Scope(unittest.TestCase):
    def test_scope_is_recorded_and_echoed(self):
        m = load(Path(tempfile.mkdtemp()))
        out = run(m, "dispatch", "--repo", "a", "--title", "a: x", "--scope", "push own repo; spend<=5USD")
        self.assertIn("scope='push own repo; spend<=5USD'", out)
        self.assertEqual(json.loads(m.BOARD.read_text())["tasks"][0]["scope"], "push own repo; spend<=5USD")


class Digest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.m = load(self.tmp)
        self.m.CAIRN.mkdir(parents=True)
        now = time.time()
        mk = lambda i, s, u: {"id": i, "title": f"r: {i}", "status": s, "started": u, "updated": u}
        self.m.BOARD.write_text(json.dumps({"next": 9, "tasks": [
            mk("t1", "done", now - 3600), mk("t2", "done", now - 5 * 86400),
            mk("t3", "waiting", now), mk("t4", "queued", now)]}))
        self.scratch = self.tmp / "proj"
        self.scratch.mkdir()

    def start(self, source="startup"):
        return run(self.m, "session-start", stdin={"session_id": "s1", "cwd": str(self.scratch), "source": source})

    def test_digest_content_and_size(self):
        d = self.m.morning_digest()
        self.assertIn("t1", d)
        self.assertNotIn("t2", d)  # finished days ago
        self.assertIn("Waiting on you (1)", d)
        self.assertIn("Queued (1)", d)
        self.assertLessEqual(len(d.splitlines()), 10)

    def test_empty_board_is_silent(self):
        self.m.BOARD.write_text(json.dumps({"next": 1, "tasks": []}))
        self.assertEqual(self.m.morning_digest(), "")

    def test_shown_once_per_day_at_startup_only(self):
        self.assertNotIn("Morning digest", self.start("resume"))
        self.assertIn("Morning digest", self.start())
        self.assertNotIn("Morning digest", self.start())


if __name__ == "__main__":
    unittest.main()
