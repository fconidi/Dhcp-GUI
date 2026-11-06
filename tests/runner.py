"""Run the unit tests without leaving bytecode or temporary files in the tree.

Usage: python3 -I tests/runner.py [unittest arguments]
Outputs go to $DHCP_GUI_TEST_DIR, or a fresh temporary directory.
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    work = Path(os.environ.get("DHCP_GUI_TEST_DIR") or tempfile.mkdtemp(prefix="dhcp-gui-tests-"))
    work.mkdir(parents=True, exist_ok=True)
    sys.pycache_prefix = str(work / "pycache")
    os.environ["TMPDIR"] = str(work)
    tempfile.tempdir = str(work)
    sys.path.insert(0, str(ROOT))
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"), top_level_dir=str(ROOT))
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
