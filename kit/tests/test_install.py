"""routine-allow is opt-in, reversible, and never touches rules the user had. Run: python -m unittest tests/test_install.py"""
import importlib.util, json, sys, tempfile, unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent.parent


def load(tmp, argv):
    spec = importlib.util.spec_from_file_location("cairn_install", HERE / "install.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    m.HOME = tmp; m.CAIRN = tmp / "cairn"; m.SETTINGS = tmp / "settings.json"; m.CLAUDE_MD = tmp / "CLAUDE.md"; m.OLD = tmp / "old"
    sys.argv = ["install.py", *argv]
    return m


class RoutineAllow(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def allow(self):
        return json.loads((self.tmp / "settings.json").read_text())["permissions"]["allow"]

    def test_default_adds_nothing_risky(self):
        load(self.tmp, []).install()
        self.assertNotIn("Bash(git commit:*)", self.allow())

    def test_opt_in_add_and_remove_keeps_user_rules(self):
        (self.tmp / "settings.json").write_text(json.dumps({"permissions": {"allow": ["Bash(git status:*)", "Bash(ls:*)"]}}))
        load(self.tmp, ["--routine-allow"]).install()
        a = self.allow()
        self.assertIn("Bash(git commit:*)", a)
        self.assertFalse([r for r in a if "push" in r or "install" in r])
        self.assertEqual(a.count("Bash(git status:*)"), 1)
        load(self.tmp, ["--uninstall"]).uninstall()
        a = self.allow()
        self.assertIn("Bash(git status:*)", a); self.assertIn("Bash(ls:*)", a)
        self.assertNotIn("Bash(git commit:*)", a)

    def test_rerun_without_flag_removes_them(self):
        load(self.tmp, ["--routine-allow"]).install()
        load(self.tmp, []).install()
        self.assertNotIn("Bash(git commit:*)", self.allow())


if __name__ == "__main__":
    unittest.main()
