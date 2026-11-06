import unittest

from dhcp_gui import i18n

try:
    import gi
    gi.require_version("Gtk", "3.0")
    from dhcp_gui.gui import window
except (ImportError, ValueError):  # pragma: no cover
    window = None

BASE = {"kea_installed": True, "kea_version": "2.6.3", "service_active": "inactive",
        "service_enabled": "enabled", "nics": [], "other_dhcp": [], "config_state": "pristine",
        "reasons": [], "writable": True}


@unittest.skipIf(window is None, "GTK not available")
class SummaryTest(unittest.TestCase):
    def test_every_state_has_a_message_in_both_languages(self):
        for state in ("pristine", "managed", "managed_modified", "importable", "unsupported"):
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


if __name__ == "__main__":
    unittest.main()
