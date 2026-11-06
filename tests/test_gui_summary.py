import unittest

from dhcp_gui import i18n

try:
    import gi
    gi.require_version("Gtk", "3.0")
    gi.require_version("Gdk", "3.0")
    from gi.repository import Gdk
    from dhcp_gui.gui import window
except (ImportError, ValueError):  # pragma: no cover
    Gdk = window = None

BASE = {"kea_installed": True, "kea_version": "2.6.3", "service_active": "inactive",
        "service_enabled": "enabled", "nics": [], "other_dhcp": [], "config_state": "pristine",
        "reasons": [], "writable": True}


@unittest.skipIf(window is None, "GTK not available")
class SummaryTest(unittest.TestCase):
    def test_every_state_has_a_message_in_both_languages(self):
        for state in ("pristine", "managed", "managed_modified", "importable", "unsupported", "unreadable"):
            for lang in ("en", "it"):
                self.assertNotEqual(i18n.translate("state_" + state, lang), "state_" + state)

    def test_missing_kea_message(self):
        lines = window.summary_lines({**BASE, "kea_installed": False})
        self.assertEqual(lines, [i18n.translate("kea_missing")])

    def test_other_dhcp_warning_and_reasons(self):
        lines = window.summary_lines({**BASE, "config_state": "unsupported", "other_dhcp": ["dnsmasq"],
                                      "reasons": ["unsupported key Dhcp4.loggers"]})
        text = "\n".join(lines)
        self.assertIn("dnsmasq", text)
        self.assertIn("Dhcp4.loggers", text)

    def test_nic_descriptions(self):
        up = {"name": "eth1", "up": True, "addresses": ["192.168.50.1/24"], "stable": True}
        self.assertIn(i18n.translate("nic_stable"), window.describe_nic(up))
        self.assertIn(i18n.translate("nic_dynamic"), window.describe_nic({**up, "stable": False}))
        self.assertIn(i18n.translate("nic_no_address"), window.describe_nic({**up, "addresses": []}))


@unittest.skipIf(window is None or Gdk is None or Gdk.Display.get_default() is None, "display not available")
class UnlockTest(unittest.TestCase):
    def test_protected_configuration_is_editable_only_after_unlock(self):
        class Helper:
            def __init__(self):
                self.calls = []

            def call(self, op, *args, **kwargs):
                self.calls.append(op)
                if op == "inventory":
                    return {**BASE, "config_state": "unreadable", "writable": False}
                if op == "inventory_private":
                    return BASE
                if op == "current":
                    return {"model": None}
                raise AssertionError(op)

        helper = Helper()
        gui = window.MainWindow(helper)
        try:
            self.assertFalse(gui.notebook.get_nth_page(1).get_sensitive())
            self.assertTrue(gui.unlock_btn.get_sensitive())
            self.assertNotIn("current", helper.calls)
            gui.on_unlock()
            self.assertTrue(gui.notebook.get_nth_page(1).get_sensitive())
            self.assertFalse(gui.unlock_btn.get_sensitive())
            self.assertEqual(helper.calls[-2:], ["inventory_private", "current"])
        finally:
            gui.destroy()


if __name__ == "__main__":
    unittest.main()
