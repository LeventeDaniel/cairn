"""Checks for cairn.py dispatch / report / board and the Home/worker hooks. Run: python -m unittest tests/test_board.py"""
import importlib.util, io, json, os, subprocess, sys, tempfile, time, unittest
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
             "prompt": m.cmd_prompt, "new-repo": m.cmd_new_repo, "session-start": m.cmd_session_start}[argv[0]]()
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

    def test_plan_usage_from_before_the_reset_is_not_reported(self):
        st = self.m.CAIRN / "state" / "u1.json"
        st.parent.mkdir(parents=True)
        base = {"t": time.time(), "pct": 5, "five_hour": 91, "seven_day": 20}
        st.write_text(json.dumps({**base, "five_hour_resets": time.time() - 60}))
        self.assertNotIn("Plan usage", self.prompt("u1", self.repo, "carry on"))
        st.write_text(json.dumps({**base, "five_hour_resets": time.time() + 600}))
        (self.m.CAIRN / "nag" / "u1.json").unlink()
        self.assertIn("Plan usage is high", self.prompt("u1", self.repo, "carry on"))

    def test_non_worker_low_context_says_nothing_about_home(self):
        out = self.prompt("other", self.repo, "also please redesign the marketing website header banner colours today")
        self.assertNotIn("Cairn Home", out)

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
