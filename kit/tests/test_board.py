"""Checks for cairn.py dispatch / report / board and the Home/worker hooks. Run: python -m unittest tests/test_board.py"""
import importlib.util, io, json, sys, tempfile, time, unittest
from contextlib import redirect_stdout
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("cairn", HERE / "cairn.py")


def load(tmp):
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
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
            {"dispatch": m.cmd_dispatch, "report": m.cmd_report, "board": m.cmd_board,
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
        rows = {r["id"]: r for r in json.loads(run(self.m, "board", "--json"))}
        self.assertEqual(rows["t1"]["status"], "waiting")
        self.assertEqual(rows["t1"]["cliSession"], "u1")
        self.assertEqual(rows["t2"]["status"], "closed")

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


if __name__ == "__main__":
    unittest.main()


class Scope(unittest.TestCase):
    def test_scope_is_recorded_and_echoed(self):
        m = load(Path(tempfile.mkdtemp()))
        out = run(m, "dispatch", "--repo", "a", "--title", "a: x", "--scope", "push own repo; spend<=5USD")
        self.assertIn("scope='push own repo; spend<=5USD'", out)
        self.assertEqual(json.loads(m.BOARD.read_text())["tasks"][0]["scope"], "push own repo; spend<=5USD")
