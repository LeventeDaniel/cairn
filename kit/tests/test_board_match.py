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
            run(self.m, "dispatch", "--repo", "a", "--title", "a: morning digest", "--again")
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
        run(self.m, "dispatch", "--repo", "a", "--title", "a: digest", "--session", "local_real", "--again")  # t2, the real one
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


class StopHook(unittest.TestCase):
    """A worker's own turn-end record on its board row (Stop hook), instead of trusting an older note."""

    def setUp(self):
        self.m = load(Path(tempfile.mkdtemp()))
        run(self.m, "dispatch", "--repo", "a", "--title", "a: long job", "--session", "local_j")

    def row(self):
        return json.loads(run(self.m, "board", "--json"))[0]

    def stop(self, sid="u1", msg="Did the thing.\n\n**All 12 tests pass, pushed abc123.**", **extra):
        run(self.m, "stop", stdin={"session_id": sid, "last_assistant_message": msg, **extra})

    def test_prompt_hook_ties_the_session_to_its_row_by_title(self):
        run(self.m, "prompt", stdin={"session_id": "u1", "cwd": str(self.m.HOME), "prompt": "go",
                                     "session_title": "A: Long Job", "transcript_path": ""})
        self.assertEqual(json.loads(self.m.BOARD.read_text())["tasks"][0]["cliSession"], "u1")
        run(self.m, "prompt", stdin={"session_id": "u2", "cwd": str(self.m.HOME), "prompt": "go",
                                     "session_title": "a: long job", "transcript_path": ""})
        self.assertEqual(json.loads(self.m.BOARD.read_text())["tasks"][0]["cliSession"], "u1")  # taken: not handed over

    def test_stop_records_the_workers_last_line(self):
        self.m._AGENTS = [agent("u1", "a: long job", "busy")]
        self.row()
        run(self.m, "report", "t1", "--note", "still running")
        b = json.loads(self.m.BOARD.read_text())
        b["tasks"][0]["updated"] -= 5   # the note is seconds old: on Windows two clock reads in a row can be equal
        self.m.BOARD.write_text(json.dumps(b))
        self.stop()
        self.m._AGENTS = [agent("u1", "a: long job", "idle")]
        r = self.row()
        self.assertEqual(r["status"], "waiting")
        self.assertEqual(r["last"], "All 12 tests pass, pushed abc123.")
        self.assertTrue(r["reportStale"])  # Home's "still running" note is older than the turn end
        self.assertIn("its last turn ended", run(self.m, "board"))

    def test_stop_from_a_session_that_is_no_worker_changes_nothing(self):
        before = self.m.BOARD.read_text()
        self.stop(sid="stranger")
        self.assertEqual(self.m.BOARD.read_text(), before)

    def test_idle_with_background_work_pending_is_running_until_it_goes_quiet(self):
        self.m._AGENTS = [agent("u1", "a: long job", "busy")]
        self.row()
        self.stop(background_tasks=[{"id": "x", "type": "shell", "status": "running"}])
        self.m._AGENTS = [agent("u1", "a: long job", "idle")]
        self.assertEqual(self.row()["status"], "running")
        b = json.loads(self.m.BOARD.read_text())
        b["tasks"][0]["turnEnded"] -= 3600  # an hour of silence: the background run is probably dead
        self.m.BOARD.write_text(json.dumps(b))
        r = self.row()
        self.assertEqual((r["status"], r["pending"]), ("waiting", 1))
        self.m._AGENTS = [agent("u1", "a: long job", "busy")]   # a new turn clears what the old one left
        self.assertNotIn("pending", self.row())


class NotTyped(unittest.TestCase):
    def test_a_message_from_another_session_is_not_a_topic_shift(self):
        m = load(Path(tempfile.mkdtemp()))
        repo = m.HOME / "r"
        repo.mkdir(parents=True)
        (repo / "SESSION.md").write_text("## Goal\nShip the invoice exporter\n")
        text = "please redesign the marketing website header banner colours today instead"
        self.assertTrue(m.topic_shift(text, repo))
        self.assertEqual(m.topic_shift('Another Claude session sent a message:\n<cross-session-message from="x">' + text, repo), "")
        self.assertEqual(m.topic_shift("<task-notification>" + text, repo), "")

    def test_no_title_nudge_for_a_session_that_is_already_titled(self):
        m = load(Path(tempfile.mkdtemp()))
        os.environ["CLAUDE_CODE_ENTRYPOINT"] = "claude-desktop"
        try:
            base = {"cwd": str(m.HOME), "prompt": "go", "transcript_path": ""}
            self.assertNotIn("Title", run(m, "prompt", stdin={**base, "session_id": "a1", "session_title": "cairn: audit gaps"}))
            self.assertNotIn("title it", run(m, "prompt", stdin={**base, "session_id": "a1", "session_title": "cairn: audit gaps"}))
            self.assertIn("title it", run(m, "prompt", stdin={**base, "session_id": "a2"}))
            self.assertIn("title it", run(m, "prompt", stdin={**base, "session_id": "a3", "session_title": "New session"}))
        finally:
            os.environ.pop("CLAUDE_CODE_ENTRYPOINT", None)


class Edges(unittest.TestCase):
    def test_new_repo_name_can_never_be_the_repos_folder_or_its_parent(self):
        m = load(Path(tempfile.mkdtemp()))
        self.assertEqual([m.repo_name(x) for x in ("..", ".", "../up", ".hidden", "my app!", "")],
                         ["project", "project", "up", "hidden", "my-app", "project"])
        m.CAIRN.mkdir(parents=True)
        ws = m.HOME / "ws"
        ws.mkdir()
        m.CFG.write_text(json.dumps({"repos_dir": str(ws)}))
        self.assertIn("CREATED project", run(m, "new-repo", "--name", ".", "--purpose", "x"))
        self.assertFalse((ws / ".git").exists())

    def test_spawn_passes_the_chosen_model_and_effort_to_a_background_session(self):
        m = load(Path(tempfile.mkdtemp()))
        here = tempfile.mkdtemp()
        with mock.patch.object(m, "claude_exe", return_value="claude"), mock.patch.object(m, "cli_logged_in", return_value=True):
            out = run(m, "spawn", "--name", "look up", "--task", "find x", "--repo", here, "--model", "haiku",
                      "--effort", "low", "--dry-run")
            self.assertIn("claude --bg --name look-up --model haiku --effort low", out)
            plain = run(m, "spawn", "--name", "look up", "--task", "find x", "--repo", here, "--dry-run")
            self.assertIn("claude --bg --name look-up\n", plain)
            self.assertIn("REFUSED", run(m, "spawn", "--name", "n", "--task", "t", "--repo", here, "--model", "haiku; rm x", "--dry-run"))

    def test_spawn_in_a_folder_claude_code_does_not_trust_says_how_to_start_it_instead(self):
        m = load(Path(tempfile.mkdtemp()))
        here = tempfile.mkdtemp()
        seen = {}

        def fake(cmd, **kw):
            seen.update(kw)
            return mock.Mock(returncode=1, stdout="", stderr="Workspace not trusted. Run `claude` in X once and accept the trust prompt, then retry.")
        with mock.patch.object(m, "claude_exe", return_value="claude"), mock.patch.object(m, "cli_logged_in", return_value=True), \
                mock.patch.object(m.subprocess, "run", side_effect=fake):
            out = run(m, "spawn", "--name", "n", "--task", "do the thing", "--repo", here)
        self.assertIn("CANNOT START", out)
        self.assertIn("app's own session tool", out)
        self.assertIn("do the thing", out)
        self.assertEqual(seen.get("encoding"), "utf-8")   # the CLI's "·" must not come back as "Â·"
        self.assertFalse((m.CAIRN / "spawned.md").exists())

    def test_audit_counts_only_this_projects_auto_memory(self):
        m = load(Path(tempfile.mkdtemp()))
        here = Path(tempfile.mkdtemp())
        enc = m.re.sub(r"[^A-Za-z0-9]", "-", m.project_root(str(here)))
        for name, lines in ((enc, 3), ("C--some-other-project", 500)):
            d = m.HOME / "projects" / name / "memory"
            d.mkdir(parents=True)
            (d / "MEMORY.md").write_text("- a fact" + chr(10) * 1 + ("- x" + chr(10)) * (lines - 1))
        old = os.getcwd()
        os.chdir(here)
        try:
            import io
            from contextlib import redirect_stdout
            buf = io.StringIO()
            with redirect_stdout(buf):
                m.cmd_audit()
        finally:
            os.chdir(old)
        out = buf.getvalue()
        self.assertEqual(out.count("Auto memory"), 1)
        self.assertNotIn("some-other-project", out)

    def test_audit_counts_the_skills_of_plugins_synced_from_the_account(self):
        # Seen live: 7 plugins synced from claude.ai listed 50 skills (~5.7k tokens) in every session, the
        # audit said "Enabled plugins (1)" and nothing about them.
        m = load(Path(tempfile.mkdtemp()))
        syn = m.HOME / "plugins" / "synced" / "org_user"
        for plugin, n in (("legal", 9), ("design", 7)):
            d = syn / plugin
            (d / ".claude-plugin").mkdir(parents=True)
            (d / ".claude-plugin" / "plugin.json").write_text(json.dumps({"name": plugin}))
            for i in range(n):
                (d / "skills" / f"s{i}").mkdir(parents=True)
                (d / "skills" / f"s{i}" / "SKILL.md").write_text(
                    "---\nname: s%d\ndescription: %s\n---\nbody that is not listed\n" % (i, "word " * 90))
        (syn / "legal" / ".mcp.json").write_text(json.dumps({"mcpServers": {"slack": {}, "box": {}}}))
        (syn / "empty").mkdir()
        (m.HOME / "plugins" / "installed_plugins.json").write_text(json.dumps({"plugins": {"x@y": [{"installPath": ""}], "bad": 3}}))
        costs = m.plugin_costs()
        self.assertEqual([(c[1], c[2], c[3]) for c in costs], [("legal", 9, 2), ("design", 7, 0)])
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        old = os.getcwd()
        os.chdir(tempfile.mkdtemp())
        try:
            with redirect_stdout(buf):
                m.cmd_audit()
        finally:
            os.chdir(old)
        out = buf.getvalue()
        self.assertIn("Plugin skill descriptions (16 skills in 2 plugins)", out)
        self.assertIn("legal (9 skills, declares 2 MCP server(s); synced from claude.ai)", out)
        self.assertIn("turn off the ones not needed", out)
        self.assertNotIn("own count", out)    # the CLI is asked only with --exact

    def test_context_table_reads_the_clis_own_count(self):
        m = load(Path(tempfile.mkdtemp()))
        text = "\n".join([
            "## Context Usage", "", "**Model:** claude-haiku-5-5  ", "**Tokens:** 33.2k / 1m (3%)", "",
            "### Estimated usage by category", "", "| Category | Tokens | Percentage |", "|----------|--------|------------|",
            "| System prompt | 3.6k | 0.4% |", "| System tools | 15.3k | 1.5% |", "| MCP tools (deferred) | 58.2k | 5.8% |",
            "| Skills | 9.9k | 1.0% |", "| Messages | 201 | 0.0% |", "| Free space | 933.8k | 93.4% |",
            "| Autocompact buffer | 33k | 3.3% |", "", "### MCP Tools", "", "| Tool | Server | Tokens |", "| a | b | 152 |"])
        self.assertEqual(m.context_table(text), ("33.2k / 1m (3%)", [("System prompt", "3.6k"), ("System tools", "15.3k"), ("Skills", "9.9k")]))
        self.assertEqual(m.context_table("not a table"), ("", []))
        self.assertEqual(m.context_table(None), ("", []))


class AgentFields(unittest.TestCase):
    """Fields of `claude agents --json` per code.claude.com/docs/en/agent-view: status busy|waiting|idle only
    while the process lives, waitingFor while a prompt is open, state for background sessions."""

    def setUp(self):
        self.m = load(Path(tempfile.mkdtemp()))
        run(self.m, "dispatch", "--repo", "a", "--title", "a: job", "--session", "local_j")
        self.m.GONE_GRACE = 0

    def row(self, **fields):
        a = {"sessionId": "u1", "name": "a: job", "startedAt": time.time() * 1000, "kind": "interactive", **fields}
        self.m._AGENTS = [{k: v for k, v in a.items() if v is not None}]
        return json.loads(run(self.m, "board", "--json"))[0]

    def test_an_open_prompt_is_recorded_and_cleared(self):
        r = self.row(status="waiting", waitingFor="permission prompt")
        self.assertEqual((r["status"], r["waitingFor"]), ("waiting", "permission prompt"))
        self.assertIn("NEEDS THE USER NOW: permission prompt", run(self.m, "board"))
        self.assertNotIn("waitingFor", self.row(status="idle"))       # answered, turn over
        self.assertNotIn("waitingFor", self.row(status="busy"))

    def test_a_prompt_beats_pending_background_work(self):
        self.row(status="busy")
        run(self.m, "stop", stdin={"session_id": "u1", "last_assistant_message": "x", "background_tasks": [{"id": "1"}]})
        self.assertEqual(self.row(status="idle")["status"], "running")
        self.assertEqual(self.row(status="waiting", waitingFor="input needed")["status"], "waiting")

    def test_a_session_whose_process_is_gone_does_not_stay_running(self):
        self.assertEqual(self.row(status="busy")["status"], "running")
        b = json.loads(self.m.BOARD.read_text())
        b["tasks"][0]["started"] -= 900
        self.m.BOARD.write_text(json.dumps(b))
        r = self.row(status=None)   # listed by --all, but no pid/status: the process has exited
        self.assertEqual(r["status"], "closed")

    def test_background_session_states(self):
        self.assertEqual(self.row(status=None, kind="background", state="working")["status"], "running")
        r = self.row(status=None, kind="background", state="blocked")
        self.assertEqual((r["status"], r["waitingFor"]), ("waiting", "input needed"))
        b = json.loads(self.m.BOARD.read_text())
        b["tasks"][0]["started"] -= 900
        self.m.BOARD.write_text(json.dumps(b))
        self.assertEqual(self.row(status=None, kind="background", state="done")["status"], "closed")


class StopFailure(unittest.TestCase):
    """A turn that ends on an API error (the usage limit) is not a finished turn (hooks docs: StopFailure)."""

    def setUp(self):
        self.m = load(Path(tempfile.mkdtemp()))
        run(self.m, "dispatch", "--repo", "a", "--title", "a: job", "--session", "local_j")
        self.m._AGENTS = [agent("u1", "a: job", "busy")]
        run(self.m, "board")
        run(self.m, "stop", stdin={"session_id": "u1", "hook_event_name": "StopFailure", "error": "rate_limit",
                                   "last_assistant_message": "API Error: Rate limit reached"})
        self.m._AGENTS = [agent("u1", "a: job", "idle")]

    def test_the_row_says_stopped_until_the_worker_runs_again(self):
        r = json.loads(run(self.m, "board", "--json"))[0]
        self.assertEqual((r["status"], r["stopped"]), ("waiting", "rate_limit"))
        out = run(self.m, "board")
        self.assertIn("STOPPED", out)
        self.assertIn("Once the usage limit has reset, tell it to continue", out)
        self.m._AGENTS = [agent("u1", "a: job", "busy")]
        self.assertNotIn("stopped", json.loads(run(self.m, "board", "--json"))[0])

    def test_a_cut_off_worker_is_never_closed_when_its_process_is_gone(self):
        # Seen live: the limit ends the turn, the process exits, and the board marked the row "closed",
        # which hid the resume hint.
        self.m.GONE_GRACE = 0
        b = json.loads(self.m.BOARD.read_text())
        b["tasks"][0]["started"] -= 900
        self.m.BOARD.write_text(json.dumps(b))
        self.m._AGENTS = [agent("zz", "other: thing", "idle")]   # its own session no longer answers
        for _ in range(2):
            r = json.loads(run(self.m, "board", "--json"))[0]
        self.assertEqual((r["status"], r["stopped"]), ("waiting", "rate_limit"))
        self.assertIn("STOPPED", run(self.m, "board"))
        # a row an older board already closed comes back when the stop hook says it was cut off
        b = json.loads(self.m.BOARD.read_text())
        b["tasks"][0].update(status="closed", closedBy="gone")
        self.m.BOARD.write_text(json.dumps(b))
        run(self.m, "stop", stdin={"session_id": "u1", "hook_event_name": "StopFailure", "error": "rate_limit"})
        self.assertEqual(json.loads(self.m.BOARD.read_text())["tasks"][0]["status"], "waiting")

    def test_an_idle_worker_that_asks_nothing_is_shown_idle_not_waiting(self):
        run(self.m, "stop", stdin={"session_id": "u1", "last_assistant_message": "Done."})  # clears the stop
        out = run(self.m, "board")
        self.assertIn(" idle ", out)
        self.assertNotIn(" waiting ", out)

    def test_home_is_told_once_and_other_sessions_are_not(self):
        run(self.m, "board")
        self.m.HOME_DIR.mkdir(parents=True)
        ask = lambda sid, cwd: run(self.m, "prompt", stdin={"session_id": sid, "cwd": str(cwd), "prompt": "status?",
                                                            "transcript_path": ""})
        first = ask("h1", self.m.HOME_DIR)
        self.assertIn("1 worker(s) were cut off by the plan's usage limit", first)
        self.assertIn("t1 'a: job'", first)
        self.assertNotIn("cut off", ask("h1", self.m.HOME_DIR))   # not on every prompt
        self.assertNotIn("cut off", ask("w9", self.m.HOME))       # only Home relays it

    def test_a_plain_stop_that_only_carries_the_limit_notice_counts_as_cut_off(self):
        run(self.m, "stop", stdin={"session_id": "u1", "hook_event_name": "Stop", "last_assistant_message": "Done."})
        run(self.m, "stop", stdin={"session_id": "u1", "hook_event_name": "Stop",
                                   "last_assistant_message": "You've hit your 5-hour limit \u00b7 resets 7:10pm (Europe/Bucharest)"})
        r = json.loads(run(self.m, "board", "--json"))[0]
        self.assertEqual(r["stopped"], "rate_limit")
        self.assertIn("resets 7:10pm", run(self.m, "board"))
        # a real answer that merely mentions a limit is not a cut-off
        run(self.m, "stop", stdin={"session_id": "u1", "last_assistant_message":
                                   "Fixed the retry.\nYou may have hit your rate limit earlier, it is handled now."})
        self.assertNotIn("stopped", json.loads(run(self.m, "board", "--json"))[0])

    def test_a_normal_stop_clears_it(self):
        run(self.m, "stop", stdin={"session_id": "u1", "hook_event_name": "Stop", "last_assistant_message": "Done."})
        r = json.loads(run(self.m, "board", "--json"))[0]
        self.assertNotIn("stopped", r)
        self.assertEqual(r["last"], "Done.")


class StillOpen(unittest.TestCase):
    """A finished worker whose session nobody archived: Home hears of it on a prompt, not only at startup."""

    def setUp(self):
        self.m = load(Path(tempfile.mkdtemp()))
        run(self.m, "dispatch", "--repo", "a", "--title", "a: job", "--session", "local_j")
        self.m._AGENTS = [agent("u1", "a: job", "busy")]
        run(self.m, "board")
        run(self.m, "report", "t1", "--status", "done", "--note", "all good")
        self.m._AGENTS = [agent("u1", "a: job", "idle")]
        run(self.m, "board")
        self.m.HOME_DIR.mkdir(parents=True)

    def ask(self, sid, cwd):
        return run(self.m, "prompt", stdin={"session_id": sid, "cwd": str(cwd), "prompt": "status?", "transcript_path": ""})

    def test_home_is_told_to_archive_it_once_and_other_sessions_are_not(self):
        first = self.ask("h1", self.m.HOME_DIR)
        self.assertIn("1 finished worker(s) are still open: t1 local_j", first)
        self.assertIn("mcp__ccd_session_mgmt__archive_session", first)
        self.assertNotIn("still open", self.ask("h1", self.m.HOME_DIR))   # not on every prompt
        self.assertNotIn("still open", self.ask("w9", self.m.HOME))       # only Home archives

    def test_nothing_is_said_once_the_session_is_gone(self):
        self.m._AGENTS = [agent("zz", "other: thing", "idle")]  # archived since the board was last read
        self.assertNotIn("still open", self.ask("h2", self.m.HOME_DIR))
        self.assertNotIn("open", json.loads(run(self.m, "board", "--json"))[0])


class Inbox(unittest.TestCase):
    def setUp(self):
        self.m = load(Path(tempfile.mkdtemp()))
        self.m.INBOX = self.m.HOME / "inbox"
        self.m.INBOX.mkdir(parents=True)
        self.box = self.m.INBOX / "r.md"

    def test_notes_are_delivered_once_and_archived(self):
        self.box.write_text("- note one")
        out = self.m.take_inbox("r")
        self.assertIn("note one", out)
        self.assertEqual(self.m.take_inbox("r"), "")
        self.assertFalse(self.box.exists())
        self.assertEqual((self.m.INBOX / "archive" / "r.md").read_text(), "- note one" + chr(10))
        self.assertEqual(list(self.m.INBOX.glob("*.taking")), [])

    def test_a_note_written_while_one_session_takes_the_inbox_is_not_lost(self):
        self.box.write_text("- first" + chr(10))
        real = Path.read_text

        def late_writer(path, *a, **k):
            text = real(path, *a, **k)
            if path.name.endswith(".taking"):   # another session passes a note right now
                with open(self.box, "a", encoding="utf-8") as f:
                    f.write("- second" + chr(10))
            return text

        with mock.patch.object(Path, "read_text", late_writer):
            self.assertNotIn("second", self.m.take_inbox("r"))
        self.assertIn("second", self.m.take_inbox("r"))   # still there for the next session

    def test_registry_is_rewritten_once_a_day_only(self):
        from datetime import date
        repo = self.m.HOME / "proj"
        repo.mkdir()
        line = f"- proj | {repo} | does things | active | "
        self.m.REGISTRY.write_text("# Repo registry" + chr(10) + line + "2026-01-01" + chr(10))
        self.assertEqual(self.m.registry_touch(str(repo)), ("proj", False))
        self.assertIn(date.today().isoformat(), self.m.REGISTRY.read_text())
        before = self.m.REGISTRY.stat().st_mtime_ns
        with mock.patch.object(self.m, "write_text_atomic", side_effect=AssertionError("rewritten")):
            self.assertEqual(self.m.registry_touch(str(repo)), ("proj", False))
        self.assertEqual(self.m.REGISTRY.stat().st_mtime_ns, before)


class HomeFlow(unittest.TestCase):
    def setUp(self):
        self.m = load(Path(tempfile.mkdtemp()))

    def test_the_same_task_is_not_dispatched_twice(self):
        run(self.m, "dispatch", "--repo", "a", "--title", "a: morning digest", "--session", "local_x")
        out = run(self.m, "dispatch", "--repo", "a", "--title", "A: Morning Digest")
        self.assertIn("ALREADY ON THE BOARD: t1", out)
        self.assertIn("local_x", out)
        self.assertEqual(len(json.loads(self.m.BOARD.read_text())["tasks"]), 1)
        self.assertIn("OK t2", run(self.m, "dispatch", "--repo", "a", "--title", "a: morning digest", "--again"))
        run(self.m, "report", "t1", "--status", "done")
        run(self.m, "report", "t2", "--status", "done")
        self.assertIn("OK t3", run(self.m, "dispatch", "--repo", "a", "--title", "a: morning digest"))  # finished ones don't block

    def test_a_freed_slot_names_the_queued_task_to_start(self):
        for i in range(4):
            out = run(self.m, "dispatch", "--repo", "a", "--title", f"a: task {i}")
        self.assertIn("QUEUED t4", out)
        self.assertNotIn("CAN START", run(self.m, "report", "t1", "--note", "halfway"))
        out = run(self.m, "report", "t1", "--status", "done", "--note", "pushed")
        self.assertIn("QUEUED TASK CAN START: t4 'a: task 3'", out)
        run(self.m, "report", "t4", "--status", "running", "--session", "local_q")
        self.assertNotIn("CAN START", run(self.m, "report", "t2", "--status", "done"))  # nothing queued any more

    def test_cairn_home_is_not_listed_as_an_unregistered_repo(self):
        self.m.HOME_DIR.mkdir(parents=True)
        other = self.m.HOME / "elsewhere"
        other.mkdir()
        self.m._AGENTS = [{**agent("h1", "Cairn Home"), "cwd": str(self.m.HOME_DIR)},
                          {**agent("o1", "scratch"), "cwd": str(other)}]
        self.assertEqual([o["title"] for o in self.m.workspace()["unregistered"]], ["scratch"])

    def test_home_start_line_says_what_each_open_row_needs(self):
        self.m.HOME_DIR.mkdir(parents=True)
        run(self.m, "dispatch", "--repo", "a", "--title", "a: one", "--session", "local_1")
        run(self.m, "dispatch", "--repo", "a", "--title", "a: two", "--session", "local_2")
        self.m._AGENTS = [{**agent("u1", "a: one", "waiting"), "waitingFor": "permission prompt"}, agent("u2", "a: two", "busy")]
        run(self.m, "board")
        run(self.m, "stop", stdin={"session_id": "u2", "hook_event_name": "StopFailure", "error": "rate_limit"})
        self.m._AGENTS = [{**agent("u1", "a: one", "waiting"), "waitingFor": "permission prompt"}, agent("u2", "a: two", "idle")]
        out = run(self.m, "session-start", stdin={"session_id": "h", "cwd": str(self.m.HOME_DIR), "source": "resume"})
        self.assertIn("t1 waiting 'a: one' (needs the user: permission prompt)", out)
        self.assertIn("t2 waiting 'a: two' (cut off by the usage limit)", out)


class PutAway(unittest.TestCase):
    """Finished workers get archived instead of piling up with their context alive."""

    def setUp(self):
        self.m = load(Path(tempfile.mkdtemp()))
        run(self.m, "dispatch", "--repo", "a", "--title", "a: job", "--session", "local_j")
        self.m._AGENTS = [agent("u1", "a: job", "busy")]
        run(self.m, "board")

    def test_report_done_says_archive_it(self):
        self.assertNotIn("ARCHIVE", run(self.m, "report", "t1", "--note", "halfway"))
        out = run(self.m, "report", "t1", "--status", "done", "--note", "pushed")
        self.assertIn("ARCHIVE IT", out)
        self.assertIn("local_j", out)
        self.assertNotIn("ARCHIVE", run(self.m, "report", "t1", "--status", "waiting", "--note", "needs OK"))

    def test_board_lists_finished_workers_whose_session_is_still_open(self):
        run(self.m, "report", "t1", "--status", "done")
        self.m._AGENTS = [agent("u1", "a: job", "idle")]
        out = run(self.m, "board")
        self.assertIn("FINISHED BUT STILL OPEN (1): t1 'a: job' local_j", out)
        self.assertIn("archive_session", out)
        self.m._AGENTS = [agent("zz", "someone else")]   # archived: its session is gone
        self.assertNotIn("STILL OPEN", run(self.m, "board"))
        dead = agent("u1", "a: job", "idle")
        del dead["status"]                               # listed by --all without a live process
        self.m._AGENTS = [dead]
        self.assertNotIn("STILL OPEN", run(self.m, "board"))

    def test_home_start_line_names_them(self):
        self.m.HOME_DIR.mkdir(parents=True)
        run(self.m, "report", "t1", "--status", "done")
        self.m._AGENTS = [agent("u1", "a: job", "idle")]
        out = run(self.m, "session-start", stdin={"session_id": "h", "cwd": str(self.m.HOME_DIR), "source": "startup"})
        self.assertIn("Finished but still open (1): t1 local_j", out)


class Levels(unittest.TestCase):
    """warn / urgent by share of the window or by tokens, whichever comes first."""

    def test_a_1m_window_warns_by_tokens_long_before_50_percent(self):
        m = load(Path(tempfile.mkdtemp()))
        c = m.cfg()
        self.assertEqual([m.ctx_level(p, 1000000, c) for p in (10, 19, 20, 39, 40, 75)], [0, 0, 1, 1, 2, 2])
        self.assertEqual([m.ctx_level(p, 200000, c) for p in (20, 49, 50, 69, 70)], [0, 0, 1, 1, 2])   # small window: the % rules
        self.assertEqual(m.ctx_level(None, 1000000, c), 0)
        self.assertEqual(m.ctx_level(45, 1000000, {**c, "warn_tokens": 0, "urgent_tokens": 0}), 0)       # switched off

    def test_the_prompt_note_names_the_tokens(self):
        m = load(Path(tempfile.mkdtemp()))
        st = m.CAIRN / "state" / "s1.json"
        st.parent.mkdir(parents=True)
        st.write_text(json.dumps({"t": time.time(), "pct": 42, "window": 1000000}))
        out = run(m, "prompt", stdin={"session_id": "s1", "cwd": str(m.HOME), "prompt": "go", "transcript_path": ""})
        self.assertIn("Context is at 42% (420k tokens)", out)
        self.assertIn("handoff", out)


if __name__ == "__main__":
    unittest.main()
