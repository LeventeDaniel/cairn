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

    def test_block_is_slim_and_routing_lives_in_the_route_skill(self):
        self.install()
        block = (self.cl / "CLAUDE.md").read_text(encoding="utf-8")
        self.assertLess(len(block), 2600)
        self.assertIn("`route` skill", block)
        self.assertNotIn("{{SPAWN}}", block)
        skill = (self.cl / "skills" / "route" / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("cairn.py", skill)
        self.assertIn("spawn --where", skill)
        self.assertNotIn("{{SPAWN}}", skill)


if __name__ == "__main__":
    unittest.main()
