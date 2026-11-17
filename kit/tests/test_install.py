"""Clean-machine checks: install.py / cairn.py against a throwaway HOME. Run: python -m unittest tests/test_install.py"""
import json, os, subprocess, sys, tempfile, unittest
from pathlib import Path

KIT = Path(__file__).resolve().parent.parent


class Install(unittest.TestCase):
    def setUp(self):
        self.home = Path(tempfile.mkdtemp())
        self.env = {**os.environ, "HOME": str(self.home), "USERPROFILE": str(self.home),
                    "CLAUDE_CODE_EXECPATH": "", "LOCALAPPDATA": str(self.home / "la")}
        self.cl = self.home / ".claude"

    def py(self, script, *args, stdin="{}"):
        return subprocess.run([sys.executable, str(script), *args], env=self.env, input=stdin,
                              capture_output=True, text=True, encoding="utf-8", cwd=self.home)

    def install(self, *a):
        r = self.py(KIT / "install.py", *a)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r

    def test_merge_idempotent_and_reversible(self):
        self.cl.mkdir()
        (self.cl / "CLAUDE.md").write_text("# mine\nkeep me\n", encoding="utf-8")
        (self.cl / "settings.json").write_text(json.dumps({"theme": "dark", "permissions": {"allow": ["Bash(ls:*)"]}}))
        self.install()
        first = json.loads((self.cl / "settings.json").read_text(encoding="utf-8"))
        self.install()
        self.assertEqual(first, json.loads((self.cl / "settings.json").read_text(encoding="utf-8")))
        md = (self.cl / "CLAUDE.md").read_text(encoding="utf-8")
        self.assertEqual(md.count("cairn:start"), 1)
        self.assertIn("keep me", md)
        self.assertNotIn("{{", md)
        self.install("--uninstall")
        self.assertEqual((self.cl / "CLAUDE.md").read_text(encoding="utf-8").strip(), "# mine\nkeep me")
        s = json.loads((self.cl / "settings.json").read_text(encoding="utf-8"))
        self.assertEqual(s, {"theme": "dark", "permissions": {"allow": ["Bash(ls:*)"]}})

    def test_stats_is_pre_approved_and_removed_again(self):
        self.install()
        allow = json.loads((self.cl / "settings.json").read_text(encoding="utf-8"))["permissions"]["allow"]
        self.assertTrue(any(r.startswith("Bash(") and " stats:*" in r for r in allow), allow)

    def test_fresh_install_runs_every_command(self):
        self.install()
        for sk in ("handoff", "pass", "repos", "dispatch"):
            self.assertTrue((self.cl / "skills" / sk / "SKILL.md").exists())
        self.assertTrue((self.cl / "agents" / "scout.md").exists())
        cairn = self.cl / "cairn" / "cairn.py"
        for cmd in (["board"], ["workspace"], ["workspace", "--json"], ["cleanup"], ["audit"],
                    ["dispatch", "--repo", "r", "--title", "t"]):
            r = self.py(cairn, *cmd)
            self.assertEqual(r.returncode, 0, (cmd, r.stderr))
            self.assertNotIn("Traceback", r.stderr)
        self.assertIn("t1", self.py(cairn, "board").stdout)

    def test_bad_settings_json_changes_nothing(self):
        self.cl.mkdir()
        (self.cl / "settings.json").write_text("{bad")
        r = self.py(KIT / "install.py")
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual((self.cl / "settings.json").read_text(), "{bad")

    def test_unknown_command_exits_2(self):
        self.install()
        self.assertEqual(self.py(self.cl / "cairn" / "cairn.py", "bogus").returncode, 2)

    def test_new_repo_dry_run_creates_nothing(self):
        self.install()
        repos = self.home / "Projects"
        r = self.py(self.cl / "cairn" / "cairn.py", "spawn", "--where", "bg", "--new-repo", "x", "--name", "my-new",
                    "--task", "t", "--dry-run")
        self.assertNotIn("Traceback", r.stderr)
        self.assertFalse((repos / "my-new").exists())
        self.assertNotIn("my-new", (self.cl / "REPOS.md").read_text(encoding="utf-8"))

    def test_stop_hook_is_installed_async_once_and_removed(self):
        self.install()
        self.install()
        hooks = json.loads((self.cl / "settings.json").read_text(encoding="utf-8"))["hooks"]
        stop = hooks["Stop"]
        self.assertEqual(len(stop), 1)
        self.assertEqual(hooks["StopFailure"], stop)  # an API error ending the turn runs the same command
        h = stop[0]["hooks"][0]
        self.assertTrue(h["command"].endswith("cairn.py stop"))
        self.assertIs(h["async"], True)  # it only writes a board row: the turn must not wait for it
        r = self.py(self.cl / "cairn" / "cairn.py", "stop", stdin=json.dumps({"session_id": "x", "last_assistant_message": "hi"}))
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""))  # no board, not a worker: silent
        self.install("--uninstall")
        self.assertNotIn("hooks", json.loads((self.cl / "settings.json").read_text(encoding="utf-8")))

    def test_install_says_when_the_installed_mod_is_older_than_this_checkout(self):
        here = json.loads((KIT.parent / ".claude-plugin" / "plugin.json").read_text(encoding="utf-8"))["version"]
        reg = self.cl / "plugins" / "installed_plugins.json"
        reg.parent.mkdir(parents=True)
        reg.write_text(json.dumps({"version": 2, "plugins": {"cairn@cairn": [{"version": "0.0.1"}]}}))
        out = self.install().stdout
        self.assertIn("claude plugin update cairn@cairn", out)
        self.assertIn(f"is 0.0.1; this checkout has {here}", out)
        # Added from a local folder: the plugin is loaded in place, so the folder's version is what counts.
        folder = self.home / "kitcopy"
        (folder / ".claude-plugin").mkdir(parents=True)
        (folder / ".claude-plugin" / "plugin.json").write_text(json.dumps({"name": "cairn", "version": "0.0.2"}))
        (self.cl / "plugins" / "known_marketplaces.json").write_text(
            json.dumps({"cairn": {"source": {"source": "directory", "path": str(folder)}}}))
        out = self.install().stdout
        self.assertIn("loaded in place from", out)
        self.assertIn("which has 0.0.2", out)
        self.assertNotIn("plugin update", out)
        (folder / ".claude-plugin" / "plugin.json").write_text(json.dumps({"name": "cairn", "version": here}))
        self.assertNotIn("loaded in place", self.install().stdout)
        (self.cl / "plugins" / "known_marketplaces.json").unlink()
        reg.write_text(json.dumps({"version": 2, "plugins": {"cairn@cairn": [{"version": here}]}}))
        self.assertNotIn("plugin update", self.install().stdout)
        reg.write_text("not json")
        self.assertNotIn("plugin update", self.install().stdout)  # unreadable: say nothing, never fail

    def test_files_are_swapped_in_whole_and_no_temp_file_is_left(self):
        self.install()
        self.install()
        left = [p.name for p in self.cl.rglob("*.cairn-tmp")]
        self.assertEqual(left, [])
        self.assertEqual((self.cl / "cairn" / "cairn.py").read_text(encoding="utf-8"),
                         (KIT / "cairn.py").read_text(encoding="utf-8"))

    def test_hook_input_is_read_as_utf8_whatever_the_console_codepage(self):
        # Windows pipes default to cp1252: "\u00b7" arrived as two wrong characters, accents in titles and folders too.
        self.install()
        cairn = self.cl / "cairn" / "cairn.py"
        board = self.cl / "cairn" / "board.json"
        board.write_text(json.dumps({"next": 2, "tasks": [{
            "id": "t1", "repo": "a", "title": "a: caf\u00e9", "kind": "small", "model": "sonnet", "effort": "low",
            "session": "", "cliSession": "u1", "status": "running", "started": 0, "updated": 0, "report": ""}]}))
        payload = json.dumps({"session_id": "u1", "last_assistant_message": "Gata \u00b7 f\u0103cut \u2713"},
                             ensure_ascii=False)
        env = {k: v for k, v in self.env.items() if k not in ("PYTHONUTF8", "PYTHONIOENCODING")}
        r = subprocess.run([sys.executable, str(cairn), "stop"], env=env, input=payload.encode("utf-8"),
                           capture_output=True, cwd=self.home)
        self.assertEqual(r.returncode, 0, r.stderr)
        last = json.loads(board.read_text(encoding="utf-8"))["tasks"][0]["last"]
        self.assertEqual(last, "Gata \u00b7 f\u0103cut \u2713")

    def test_block_is_slim_and_routing_lives_in_the_route_skill(self):
        self.install()
        block = (self.cl / "CLAUDE.md").read_text(encoding="utf-8")
        self.assertLess(len(block), 1100)
        self.assertIn("`route` skill", block)
        self.assertNotIn("{{SPAWN}}", block)
        skill = (self.cl / "skills" / "route" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("cairn.py", skill)
        self.assertIn("spawn --where", skill)
        self.assertNotIn("{{SPAWN}}", skill)


if __name__ == "__main__":
    unittest.main()
