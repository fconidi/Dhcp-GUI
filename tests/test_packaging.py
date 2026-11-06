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

    def test_menu_entry_matches_the_other_syslinuxos_tools(self):
        import xml.etree.ElementTree as ET
        menu = ET.parse(ROOT / "packaging/dhcp-gui.menu").getroot()
        self.assertEqual(menu.findtext("Name"), "Applications")
        sub = menu.find("Menu")
        self.assertEqual(sub.findtext("Name"), "SysLinuxOS Tools")
        # MATE only shows the submenu with the shared directory file, as the other Tools do
        self.assertEqual(sub.findtext("Directory"), "syslinuxos-tools.directory")
        listed = [f.text for f in sub.iter("Filename")]
        self.assertEqual(listed, ["dhcp-gui.desktop"])
        desktop = (ROOT / "packaging/dhcp-gui.desktop").read_text()
        self.assertIn("Categories=Network;X-SysLinuxOS-Networking;", desktop)
        self.assertNotIn("OnlyShowIn", desktop)
        self.assertNotIn("NoDisplay", desktop)
        build = _load_build()
        self.assertTrue((ROOT / "packaging" / listed[0]).is_file())
        self.assertTrue((ROOT / "data/dhcp-gui.svg").is_file())

    def test_built_package_installs_menu_desktop_icon_and_launcher(self):
        import subprocess
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            out = subprocess.run(["python3", str(ROOT / "build-deb.py"), "--output-dir", tmp],
                                 capture_output=True, text=True, check=True).stdout.strip().splitlines()[-1]
            listing = subprocess.run(["dpkg-deb", "-c", out], capture_output=True, text=True, check=True).stdout
        for path in ("./etc/xdg/menus/applications-merged/dhcp-gui.menu", "./usr/share/applications/dhcp-gui.desktop",
                     "./usr/share/icons/hicolor/scalable/apps/dhcp-gui.svg", "./usr/bin/dhcp-gui"):
            self.assertIn(path, listing)


if __name__ == "__main__":
    unittest.main()
