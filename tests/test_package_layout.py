import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class LayoutTest(unittest.TestCase):
    def test_version_is_declared(self):
        text = (ROOT / "dhcp_gui" / "__init__.py").read_text(encoding="utf-8")
        self.assertRegex(text, r'__version__ = "\d+\.\d+\.\d+"')

    def test_user_documents_exist(self):
        for name in ("README.md", "CHANGELOG.md", "LICENSE"):
            self.assertTrue((ROOT / name).is_file(), name)


if __name__ == "__main__":
    unittest.main()
