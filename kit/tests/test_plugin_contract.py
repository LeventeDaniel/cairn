"""The mod's state contract (types/index.d.ts) must pass `claude plugin validate`: self-contained, every
state key declared. These are the two rules it failed on; the full check is `claude plugin validate .`."""
import re, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent


class Contract(unittest.TestCase):
    def setUp(self):
        self.types = (ROOT / "types" / "index.d.ts").read_text(encoding="utf-8")

    def test_types_file_is_self_contained(self):
        body = re.sub(r"/\*.*?\*/|//[^\n]*", "", self.types, flags=re.S)
        bad = re.search(r"\bimport\s*\(|^\s*import\s|\brequire\s*\(|export\s+.*\sfrom\s|///\s*<reference", body, re.M)
        self.assertIsNone(bad)

    def test_every_state_key_the_mod_uses_is_declared(self):
        src = "".join(p.read_text(encoding="utf-8") for p in (ROOT / "hooks").glob("*.ts*") if ".test." not in p.name)
        keys = set(re.findall(r"plugin:\s*'cairn',\s*key:\s*'(\w+)'", src))
        self.assertTrue(keys)
        state = self.types[self.types.index("interface PluginState"):]
        missing = sorted(k for k in keys if not re.search(r"^\s*" + k + r"\s*:", state, re.M))
        self.assertEqual(missing, [])


if __name__ == "__main__":
    unittest.main()
