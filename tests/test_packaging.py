import importlib.util
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_build():
    spec = importlib.util.spec_from_file_location("build_deb", ROOT / "build-deb.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PackagingTest(unittest.TestCase):
    def test_every_python_module_is_listed_in_the_build_script(self):
        listed = set(_load_build().MODULES)
        found = {str(p.relative_to(ROOT / "dhcp_gui")) for p in (ROOT / "dhcp_gui").rglob("*.py")}
        self.assertEqual(listed, found)

    def test_control_depends(self):
        control = (ROOT / "packaging/control").read_text()
        self.assertIn("Version: @VERSION@", control)
        depends = re.search(r"^Depends: (.*)$", control, re.M).group(1)
        for needed in ("python3", "python3-gi", "gir1.2-gtk-3.0", "pkexec", "kea-dhcp4-server"):
            self.assertIn(needed, depends)

    def test_policy_actions_match_helpers_and_client(self):
        policy = (ROOT / "packaging/com.syslinuxos.dhcp-gui.policy").read_text()
        for mode, auth in (("read", "auth_admin_keep"), ("write", "auth_admin")):
            self.assertIn(f">/usr/lib/dhcp-gui/dhcp-gui-helper-{mode}<", policy)
            self.assertIn(f'id="com.syslinuxos.dhcp-gui.{mode}"', policy)
            self.assertIn(f"<allow_active>{auth}</allow_active>", policy)
            first = (ROOT / f"packaging/dhcp-gui-helper-{mode}").read_text().splitlines()
            self.assertEqual(first[0], "#!/usr/bin/python3 -I")
            self.assertIn(f'main("{mode}")', "\n".join(first))
        from dhcp_gui.gui.helper_client import PKEXEC
        self.assertEqual(PKEXEC["read"], ["pkexec", "/usr/lib/dhcp-gui/dhcp-gui-helper-read"])
        self.assertEqual(PKEXEC["write"], ["pkexec", "/usr/lib/dhcp-gui/dhcp-gui-helper-write"])

    def test_desktop_entry_and_menu(self):
        desktop = (ROOT / "packaging/dhcp-gui.desktop").read_text()
        self.assertIn("Exec=dhcp-gui\n", desktop)
        self.assertIn("Icon=dhcp-gui\n", desktop)
        self.assertIn("<Filename>dhcp-gui.desktop</Filename>", (ROOT / "packaging/dhcp-gui.menu").read_text())


if __name__ == "__main__":
    unittest.main()
