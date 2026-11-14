"""Board ↔ live-session matching, the board lock and Windows-safe writes. Run: python -m unittest discover -s tests"""
import json, os, tempfile, threading, time, unittest
from pathlib import Path
from unittest import mock

from test_board import load, run


def agent(sid, name, status="idle", started=None):
    return {"sessionId": sid, "name": name, "status": status, "startedAt": (started or time.time()) * 1000}


class Match(unittest.TestCase):
    def setUp(self):
        self.m = load(Path(tempfile.mkdtemp()))

    def rows(self):
        return {r["id"]: r for r in json.loads(run(self.m, "board", "--json"))}

    def age(self, **secs):
        b = json.loads(self.m.BOARD.read_text())
        for t in b["tasks"]:
            if t["id"] in secs:
                t["started"] -= secs[t["id"]]
        self.m.BOARD.write_text(json.dumps(b))

    def test_one_live_session_serves_one_task(self):
        # Seen live: two duplicate rows with no session borrowed the session of the real task with the
        # same title, and all three sat under "Needs you".
        for _ in range(3):
            run(self.m, "dispatch", "--repo", "a", "--title", "a: morning digest")
        self.age(t1=900, t2=600, t3=400)
        self.m._AGENTS = [agent("u9", "a: morning digest")]
        r = self.rows()
        self.assertEqual((r["t3"]["status"], r["t3"]["cliSession"]), ("waiting", "u9"))
        self.assertEqual(r["t1"]["status"], "closed")
        self.assertEqual(r["t2"]["status"], "closed")
        self.assertNotIn("cliSession", r["t1"])

    def test_finished_task_keeps_its_session_from_a_new_task_with_the_same_title(self):
        run(self.m, "dispatch", "--repo", "a", "--title", "a: push")
        self.m._AGENTS = [agent("u1", "a: push", "busy")]
        self.rows()
        run(self.m, "report", "t1", "--status", "done")
        run(self.m, "dispatch", "--repo", "a", "--title", "a: push")
        self.m._AGENTS = [agent("u1", "a: push", "idle")]
        r = self.rows()
        self.assertEqual(r["t2"]["status"], "running")  # just dispatched, its own session not up yet
        self.assertNotIn("cliSession", r["t2"])

    def test_long_title_matches_the_name_the_cli_cuts_at_40(self):
        title = "a: audit public repo for sensitive data and more"
        run(self.m, "dispatch", "--repo", "a", "--title", title)
        self.age(t1=600)
        self.m._AGENTS = [agent("u1", title[:40], "busy", time.time() - 500)]
        r = self.rows()
        self.assertEqual((r["t1"]["status"], r["t1"]["cliSession"]), ("running", "u1"))
        self.assertFalse(self.m.same_title("a: audit", "a: audit public"))  # a short name is not a prefix match

    def test_report_with_a_new_session_drops_the_old_match(self):
        run(self.m, "dispatch", "--repo", "a", "--title", "a: x", "--session", "local_one")
        self.m._AGENTS = [agent("u1", "a: x", "busy")]
        self.rows()
        run(self.m, "report", "t1", "--session", "local_two")
        self.assertNotIn("cliSession", json.loads(self.m.BOARD.read_text())["tasks"][0])


class Lock(unittest.TestCase):
    def setUp(self):
        self.m = load(Path(tempfile.mkdtemp()))
        self.m.CAIRN.mkdir(parents=True)

    def test_lock_is_exclusive_and_released(self):
        order = []

        def other():
            with self.m.board_lock() as l2:
                order.append(("other", l2.held))

        with self.m.board_lock() as l1:
            self.assertTrue(l1.held)
            th = threading.Thread(target=other)
            th.start()
            time.sleep(0.2)
            order.append(("first-done", True))
        th.join(5)
        self.assertEqual(order, [("first-done", True), ("other", True)])
        self.assertFalse((self.m.CAIRN / "board.lock").exists())

    def test_stale_lock_is_taken_over(self):
        lock = self.m.CAIRN / "board.lock"
        lock.write_text("")
        old = time.time() - 120
        os.utime(lock, (old, old))
        with self.m.board_lock() as l:
            self.assertTrue(l.held)

    def test_refresh_does_not_undo_a_report_made_while_the_cli_was_answering(self):
        # The pane refreshes the board every few seconds; `claude agents` takes seconds to answer.
        # A report Home made in that gap used to be overwritten with the copy read before it.
        run(self.m, "dispatch", "--repo", "a", "--title", "a: x")
        m = self.m
        m._AGENTS = None

        def slow_agents():
            b = json.loads(m.BOARD.read_text())
            b["tasks"][0].update(status="done", report="finished")  # Home's report lands mid-refresh
            m.BOARD.write_text(json.dumps(b))
            m._AGENTS = [agent("u1", "a: x", "idle")]
            return m._AGENTS

        with mock.patch.object(m, "live_agents", side_effect=slow_agents):
            rows = m.board_rows()
        self.assertEqual((rows[0]["status"], rows[0]["report"]), ("done", "finished"))


class Writes(unittest.TestCase):
    def test_replace_is_retried_when_windows_says_the_file_is_busy(self):
        m = load(Path(tempfile.mkdtemp()))
        real, calls = os.replace, []

        def flaky(a, b):
            calls.append(1)
            if len(calls) < 3:
                raise PermissionError("in use")
            real(a, b)

        with mock.patch.object(m.os, "replace", side_effect=flaky):
            m.write_json(m.CAIRN / "state" / "last.json", {"ok": 1})
        self.assertEqual(json.loads((m.CAIRN / "state" / "last.json").read_text()), {"ok": 1})

    def test_gives_up_quietly_and_leaves_no_temp_file(self):
        m = load(Path(tempfile.mkdtemp()))
        with mock.patch.object(m.os, "replace", side_effect=PermissionError("in use")):
            m.write_json(m.CAIRN / "state" / "last.json", {"ok": 1})  # must not raise
        self.assertEqual(list((m.CAIRN / "state").glob("*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
