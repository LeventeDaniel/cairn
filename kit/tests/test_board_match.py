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
        self.m.GONE_GRACE = 0
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

    def test_a_duplicate_that_borrowed_the_session_id_gives_it_back(self):
        run(self.m, "dispatch", "--repo", "a", "--title", "a: digest")                          # t1, duplicate, no session
        run(self.m, "dispatch", "--repo", "a", "--title", "a: digest", "--session", "local_real")  # t2, the real one
        b = json.loads(self.m.BOARD.read_text())
        b["tasks"][0].update(cliSession="u9", status="waiting", started=b["tasks"][0]["started"] - 900)
        b["tasks"][1].update(cliSession="u9")
        self.m.BOARD.write_text(json.dumps(b))
        self.m._AGENTS = [agent("u9", "a: digest", "busy")]
        self.m.GONE_GRACE = 0
        r = self.rows()
        self.assertEqual((r["t2"]["status"], r["t2"]["cliSession"]), ("running", "u9"))
        self.assertEqual(r["t1"]["status"], "closed")
        self.assertNotIn("cliSession", r["t1"])

    def test_one_short_answer_from_the_cli_does_not_close_a_live_worker(self):
        run(self.m, "dispatch", "--repo", "a", "--title", "a: long job", "--session", "local_j")
        self.age(t1=900)
        self.m._AGENTS = [agent("u1", "a: long job", "busy", time.time() - 800)]
        self.assertEqual(self.rows()["t1"]["status"], "running")
        self.m._AGENTS = [agent("zz", "someone else")]           # our session is missing from this answer
        self.assertEqual(self.rows()["t1"]["status"], "running")  # first miss: only noted
        self.m._AGENTS = [agent("u1", "a: long job", "idle", time.time() - 800)]
        r = self.rows()["t1"]
        self.assertEqual(r["status"], "waiting")
        self.assertNotIn("goneSince", r)

    def test_gone_for_good_closes_after_the_grace_and_can_come_back(self):
        run(self.m, "dispatch", "--repo", "a", "--title", "a: job", "--session", "local_j")
        self.age(t1=900)
        self.m._AGENTS = [agent("zz", "someone else")]
        self.rows()
        b = json.loads(self.m.BOARD.read_text())
        b["tasks"][0]["goneSince"] -= 300
        self.m.BOARD.write_text(json.dumps(b))
        self.assertEqual(self.rows()["t1"]["status"], "closed")
        self.m._AGENTS = [agent("u1", "a: job", "busy", time.time() - 800)]   # resumed: an auto-close is not final
        self.assertEqual(self.rows()["t1"]["status"], "running")

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
