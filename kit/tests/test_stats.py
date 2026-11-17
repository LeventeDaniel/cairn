"""`cairn.py stats`: results counted from transcripts, the ledger and the board. Run: python -m unittest discover -s tests"""
import json, os, tempfile, time, unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from test_board import load, run

T0 = time.time() - 3600


def iso(t):
    return datetime.fromtimestamp(t, timezone.utc).isoformat().replace("+00:00", "Z")


def prompt(t, origin="human"):
    return {"type": "user", "promptSource": "sdk", "turnOrigin": origin, "timestamp": iso(t), "message": {"content": "go"}}


def reply(t, mid, ctx, write=0):
    return {"type": "assistant", "timestamp": iso(t), "message": {"id": mid, "usage": {
        "input_tokens": 0, "cache_read_input_tokens": ctx - write, "cache_creation_input_tokens": write, "output_tokens": 10,
        "cache_creation": {"ephemeral_1h_input_tokens": write, "ephemeral_5m_input_tokens": 0}}}}


def boundary(t, before, secs=60):
    return {"type": "system", "subtype": "compact_boundary", "timestamp": iso(t),
            "compactMetadata": {"trigger": "manual", "preTokens": before, "durationMs": secs * 1000}}


def notice(t, mid):
    return {"type": "assistant", "isApiErrorMessage": True, "timestamp": iso(t), "message": {
        "id": mid, "content": [{"type": "text", "text": "You've hit your 5-hour limit · resets 3pm"}], "usage": {"input_tokens": 0}}}


CAIRN_NOTE = {"type": "attachment", "timestamp": iso(T0), "text": "[Cairn · Router] This session: repo 'a'"}


def transcript(m, sid, entries, project="C--r-a"):
    d = m.HOME / "projects" / project
    d.mkdir(parents=True, exist_ok=True)
    f = d / f"{sid}.jsonl"
    f.write_text("\n".join(json.dumps(e) for e in entries) + "\n", encoding="utf-8")
    return f


CHR10 = chr(10)


def ledger(m, *events):
    p = m.CAIRN / "state" / "ledger.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(list(events)), encoding="utf-8")


def long_session(replies_after=30, gap=120, before=250000, after=90000, write=40000):
    """A session that grew to `before`, was compacted `gap` seconds after its last reply, and went on."""
    e = [CAIRN_NOTE, prompt(T0), reply(T0 + 10, "m1", 80000), reply(T0 + 20, "m2", before)]
    e.append(boundary(T0 + 20 + gap + 60, before))
    for i in range(replies_after):
        e.append(reply(T0 + 200 + gap + i, f"n{i}", after + i * 100, write if i == 0 else 0))
    return e


class Facts(unittest.TestCase):
    def setUp(self):
        self.m = load(Path(tempfile.mkdtemp()))

    def test_a_reply_written_in_several_entries_counts_once_and_a_compaction_knows_what_followed(self):
        e = [prompt(T0), reply(T0 + 10, "m1", 80000), reply(T0 + 11, "m1", 80000),   # one reply, two content blocks
             reply(T0 + 20, "m2", 200000), boundary(T0 + 200, 200000, secs=60),
             reply(T0 + 300, "m3", 90000, write=40000), reply(T0 + 310, "m4", 95000),
             notice(T0 + 320, "e1"), notice(T0 + 321, "e2")]                           # one cut-off, retried
        f = self.m.session_facts(transcript(self.m, "s1", e))
        self.assertEqual((f["replies"], f["read"], f["peak"], f["now"], f["firstCtx"]), (4, 465000, 200000, 95000, 80000))
        c = f["comps"][0]
        self.assertEqual((c["before"], c["after"], c["replies"], c["w1h"], c["gapMin"]), (200000, 90000, 2, 40000, 2))
        self.assertEqual(f["limits"], 1)
        self.assertFalse(f["headless"])

    def test_a_damaged_transcript_is_read_as_far_as_it_goes(self):
        f = transcript(self.m, "s1", [prompt(T0), reply(T0 + 1, "m1", 50000)])
        with open(f, "a", encoding="utf-8") as h:
            h.write('{"type": "assistant", "message": {"usage": \n[1, 2]\n"assistant"\n{"type": "assistant", "message": 7}\n')
        self.assertEqual(self.m.session_facts(f)["replies"], 1)
        self.assertEqual(self.m.session_facts(self.m.HOME / "missing.jsonl")["replies"], 0)

    def test_an_unchanged_transcript_is_not_read_twice(self):
        transcript(self.m, "s1", [prompt(T0), reply(T0 + 1, "m1", 50000)])
        self.assertEqual(self.m.all_facts(30)["s1"]["replies"], 1)
        with mock.patch.object(self.m, "session_facts", side_effect=AssertionError("read again")):
            self.assertEqual(self.m.all_facts(30)["s1"]["replies"], 1)


class Results(unittest.TestCase):
    def setUp(self):
        self.m = load(Path(tempfile.mkdtemp()))

    def test_only_what_the_ledger_says_cairn_started_is_credited_to_cairn(self):
        e = long_session()
        transcript(self.m, "s1", e)
        transcript(self.m, "s2", e)   # the same thing, compacted by the app
        t = next(x for x in e if x.get("subtype") == "compact_boundary")
        at = datetime.fromisoformat(t["timestamp"].replace("Z", "+00:00")).timestamp()
        ledger(self.m, {"kind": "compaction", "t": at * 1000 + 2000, "sid": "s1", "by": "cairn", "before": 250000, "after": 20000},
               {"kind": "compaction", "t": at * 1000 + 2000, "sid": "s2", "by": "app", "before": 250000, "after": 20000})
        r = self.m.results(30)
        c, o = r["compactions"]["cairn"], r["compactions"]["other"]
        self.assertEqual((c["n"], o["n"]), (1, 1))
        # counted, not modelled: 160k removed (250k before, 90k at the first reply after) x the 30 replies that followed
        self.assertEqual((c["removed"], c["followed"], c["avoided"]), (160000, 30, 4800000))
        # cost: the summary read 250k cached, and the next reply wrote 40k of cache again (a 1-hour write = 20 reads)
        self.assertEqual(c["cost"], 250000 + 40000 * 19)
        self.assertEqual((c["paid"], c["lost"], c["wasted"]), (1, 0, 0))
        self.assertTrue(r["verdict"].startswith("USEFUL"), r["verdict"])
        self.assertIn("1 paid for themselves, 0 did not", "\n".join(r["lines"]))

    def test_a_cold_compaction_nobody_came_back_to_is_a_loss(self):
        transcript(self.m, "s1", long_session(replies_after=0, gap=3 * 3600))
        ledger(self.m, {"kind": "compaction", "t": (T0 + 20 + 3 * 3600 + 60) * 1000, "sid": "s1", "by": "cairn"})
        r = self.m.results(30)
        c = r["compactions"]["cairn"]
        self.assertEqual((c["n"], c["followed"], c["avoided"], c["wasted"], c["lost"]), (1, 0, 0, 1, 1))
        self.assertEqual(c["cost"], 250000 * 10)   # the whole history, uncached, for nothing
        self.assertTrue(r["verdict"].startswith("NOT PROVEN YET"), r["verdict"])

    def test_near_floor_compactions_show_as_a_loss(self):
        # Seen live: Cairn Home compacted 95k -> 85k after every turn; each one re-wrote 39k of cache.
        transcript(self.m, "s1", long_session(replies_after=3, before=95000, after=85000, write=39000))
        ledger(self.m, {"kind": "compaction", "t": (T0 + 200) * 1000, "sid": "s1", "by": "cairn"})
        r = self.m.results(30)
        self.assertEqual(r["compactions"]["cairn"]["lost"], 1)
        self.assertTrue(r["verdict"].startswith("NOT USEFUL SO FAR"), r["verdict"])

    def test_with_nothing_on_record_it_says_not_proven_and_not_measured(self):
        r = self.m.results(30)
        self.assertTrue(r["verdict"].startswith("NOT PROVEN"), r["verdict"])
        text = "\n".join(r["lines"])
        for what in ("Cairn's own text per session: not measured", "New session size: not measured",
                     "Dispatch to done: not measured yet", "A/B benchmark: not measured", "Finished workers closed: not measured"):
            self.assertIn(what, text)
        self.assertNotIn("$", text)

    def test_headless_runs_are_left_out_and_cairns_text_is_charged_only_where_it_was(self):
        transcript(self.m, "h1", [prompt(T0, "sdk"), reply(T0 + 1, "m1", 46000)])                 # a `claude -p` run
        transcript(self.m, "old", [prompt(T0), reply(T0 + 1, "m1", 50000), reply(T0 + 2, "m2", 60000)])  # before Cairn
        transcript(self.m, "new", [CAIRN_NOTE, prompt(T0), reply(T0 + 1, "m1", 50000)])
        st = self.m.CAIRN / "state"
        st.mkdir(parents=True, exist_ok=True)
        arm = {"usd": 0.005, "turns": 3, "ctxAvg": 1, "cacheRead": 1, "cacheWrite": 22000, "out": 1}
        (st / "measured.json").write_text(json.dumps({"bench": {"runs": 12, "model": "haiku", "off": arm,
                                                                 "on": {**arm, "usd": 0.0055, "cacheWrite": 23300}},
                                                      "scenario": {"runs": 1, "model": "haiku", "stageCount": 5,
                                                                   "oneSession": 0.106, "stages": 0.049}}))
        r = self.m.results(30)
        self.assertEqual((r["sessions"], r["headless"], r["replies"]), (2, 1, 3))
        self.assertEqual((r["perSessionOverhead"], r["withCairn"]["replies"], r["overhead"]), (1300, 1, 1300))
        text = "\n".join(r["lines"])
        self.assertIn("$0.0050 without Cairn, $0.0055 with (+10%)", text)
        self.assertIn("$0.106 as one long session, $0.049 as hand-off stages (-54%)", text)
        self.assertIn("On short one-off tasks it only costs (+10% in the A/B)", r["verdict"])

    def test_finished_tasks_and_cut_off_workers_are_tallied_past_the_board(self):
        m = self.m
        run(m, "dispatch", "--repo", "a", "--title", "a: one")
        run(m, "dispatch", "--repo", "a", "--title", "a: two")
        b = json.loads(m.BOARD.read_text())
        b["tasks"][0]["started"] -= 600
        b["tasks"][1]["cliSession"] = "w2"
        m.BOARD.write_text(json.dumps(b))
        run(m, "report", "t1", "--status", "done")
        for _ in range(2):   # the same cut-off reported twice counts once
            run(m, "stop", stdin={"session_id": "w2", "hook_event_name": "StopFailure", "error": "rate_limit"})
        row = json.loads(m.BOARD.read_text())["tasks"][0]
        self.assertAlmostEqual(row["doneAt"] - row["started"], 600, delta=5)
        m.BOARD.write_text(json.dumps({"tasks": [], "next": 3}))   # the rows have left the board
        r = m.results(30)
        self.assertEqual((r["board"]["routed"], r["board"]["finished"], r["board"]["stops"]), (2, 1, 1))
        self.assertIn("Tasks routed by Cairn Home: 2, finished 1", "\n".join(r["lines"]))
        self.assertIn("Dispatch to done: median 10 min (n=1)", "\n".join(r["lines"]))
        run(m, "dispatch", "--repo", "a", "--title", "a: three")
        run(m, "report", "t3", "--status", "done")
        run(m, "report", "t3", "--status", "running")   # reopened: not finished after all
        self.assertEqual(m.results(30)["board"]["finished"], 1)

    def test_stats_prints_the_verdict_and_takes_one_size_reading_a_day(self):
        m = self.m
        transcript(m, "s1", long_session())
        cats = [("System tools", "15.3k"), ("Skills", "9.9k"), ("Memory files", "724")]
        with mock.patch.object(m, "context_exact", return_value=("33.2k / 1m (3%)", cats)) as ask:
            out = run(m, "stats")
            run(m, "stats")
        self.assertEqual(ask.call_count, 1)
        self.assertIn("VERDICT  NOT PROVEN", out)
        self.assertIn("New session size (Claude Code's own count): 26k tokens", out)
        self.assertIn("first reading, nothing to compare yet", out)
        self.assertIn("Per session (largest first)", out)
        log = json.loads((m.CAIRN / "state" / "baseline.json").read_text())
        log.insert(0, {"t": time.time() - 5 * 86400, "cwd": "x", "total": 31000})
        (m.CAIRN / "state" / "baseline.json").write_text(json.dumps(log))
        self.assertIn("31k on ", run(m, "stats", "--no-measure"))
        self.assertIn("(-5k)", run(m, "stats", "--no-measure"))
        self.assertEqual(json.loads(run(m, "stats", "--no-measure", "--json"))["sessions"], 1)

    def test_the_panes_list_carries_the_results(self):
        transcript(self.m, "s1", long_session())
        w = json.loads(run(self.m, "workspace", "--json"))
        self.assertTrue(w["results"]["verdict"].startswith("NOT PROVEN"))
        self.assertTrue(any("1 sessions" in line for line in w["results"]["lines"]))

    def test_compactions_the_mod_left_undone_are_counted(self):
        now = time.time() * 1000
        ledger(self.m, {"kind": "skip", "t": now, "sid": "s1", "why": "below-payback", "tokens": 90000},
               {"kind": "skip", "t": now, "sid": "s1", "why": "below-payback", "tokens": 95000},
               {"kind": "skip", "t": now, "sid": "s2", "why": "cache-expired", "tokens": 300000},
               {"kind": "skip", "t": now - 90 * 86400000, "sid": "s3", "why": "cache-expired", "tokens": 1})
        r = self.m.results(30)
        self.assertEqual(r["skipped"], {"cache-expired": 1, "below-payback": 2})
        self.assertIn("2 too little above the floor, 1 cache already expired", CHR10.join(r["lines"]))

    def test_the_workspace_goal_is_read_from_a_worktrees_session_md_too(self):
        m = self.m
        repo = Path(tempfile.mkdtemp())
        m.REGISTRY.write_text(f"- a | {repo} | test | {time.strftime('%Y-%m-%d')}" + CHR10, encoding="utf-8")
        wt = repo / ".claude" / "worktrees" / "w1"
        wt.mkdir(parents=True)
        (wt / "SESSION.md").write_text(CHR10.join(["## Goal", "Fix the board", "", "## Next", "ship", ""]), encoding="utf-8")
        r = json.loads(run(m, "workspace", "--json"))["repos"][0]
        self.assertEqual((r["goal"], r["next"]), ("Fix the board", "ship"))
        (repo / "SESSION.md").write_text(CHR10.join(["## Goal", "Main goal", ""]), encoding="utf-8")
        os.utime(wt / "SESSION.md", (time.time() - 100, time.time() - 100))
        self.assertEqual(json.loads(run(m, "workspace", "--json"))["repos"][0]["goal"], "Main goal")

    def test_a_headless_run_is_not_listed_as_a_session_of_the_repo(self):
        # Seen live: benchmark runs and Cairn's own /context reading showed in the pane as closed sessions.
        m = self.m
        repo = Path(tempfile.mkdtemp())
        m.REGISTRY.write_text(f"- a | {repo} | test | {time.strftime('%Y-%m-%d')}\n", encoding="utf-8")
        enc = m.re.sub(r"[^A-Za-z0-9]", "-", str(repo))
        transcript(m, "real", [prompt(T0), reply(T0 + 1, "m1", 50000)], project=enc)
        transcript(m, "bench", [prompt(T0, "sdk"), reply(T0 + 1, "m1", 46000)], project=enc)
        w = json.loads(run(m, "workspace", "--json"))
        self.assertEqual([s["id"] for s in w["repos"][0]["sessions"]], ["real"])

    def test_pruning_old_state_keeps_the_ledger_the_benchmark_and_the_tallies(self):
        st = self.m.CAIRN / "state"
        st.mkdir(parents=True)
        old = time.time() - 90 * 86400
        for name in ("ledger.json", "measured.json", "tally.json", "baseline.json", "usage-days.json", "0a1b2c3d-session.json"):
            (st / name).write_text("{}")
            os.utime(st / name, (old, old))
        self.m.prune_state()
        self.assertEqual(sorted(p.name for p in st.iterdir()),
                         ["baseline.json", "ledger.json", "measured.json", "tally.json", "usage-days.json"])


class NoPrompts(unittest.TestCase):
    """The user is never asked to compact or clear: Cairn (or Claude Code) does it, the hook only keeps SESSION.md current."""

    def note(self, via):
        m = load(Path(tempfile.mkdtemp()))
        st = m.CAIRN / "state" / "s1.json"
        st.parent.mkdir(parents=True)
        st.write_text(json.dumps({"t": time.time(), "pct": 75, "window": 200000, **({"via": via} if via else {})}))
        return run(m, "prompt", stdin={"session_id": "s1", "cwd": str(m.HOME), "prompt": "go", "transcript_path": ""})

    def test_a_full_context_never_makes_the_hook_ask_for_clear(self):
        for via in ("cairn", ""):
            out = self.note(via)
            self.assertIn("Context is at 75%", out)
            self.assertIn("handoff", out)
            self.assertNotIn("/clear", out)
            self.assertNotIn("tell the user", out)
        self.assertIn("Ask the user nothing", self.note("cairn"))
        self.assertIn("Don't ask the user to compact or clear", self.note(""))

    def test_the_standing_rules_and_the_handoff_skill_ask_nothing_either(self):
        kit = Path(__file__).resolve().parent.parent
        block = (kit / "CLAUDE-block.md").read_text(encoding="utf-8")
        self.assertNotIn("type /clear", block)
        self.assertNotIn("offer Archive", block)
        self.assertIn("whether to compact/clear", block)
        self.assertNotIn("type /clear", (kit / "skills" / "handoff" / "SKILL.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
