import unittest

from dhcp_gui import i18n
from dhcp_gui.gui import viewmodel

BASE = {"kea_installed": True, "kea_version": "2.6.3", "service_active": "inactive",
        "service_enabled": "enabled", "nics": [], "other_dhcp": [], "config_state": "pristine",
        "reasons": [], "writable": True, "token": "x"}


class ViewModelTest(unittest.TestCase):
    def test_every_state_has_a_message_in_both_languages(self):
        for state in ("pristine", "managed", "managed_modified", "importable", "unsupported"):
            for lang in ("en", "it"):
                self.assertNotEqual(i18n.translate("state_" + state, lang), "state_" + state)

    def test_service_state(self):
        self.assertEqual(viewmodel.service_state(BASE)[0], "stopped")
        self.assertEqual(viewmodel.service_state({**BASE, "service_active": "active"})[0], "running")
        self.assertEqual(viewmodel.service_state({**BASE, "service_active": "weird"})[0], "problem")
        self.assertEqual(viewmodel.service_state({**BASE, "kea_installed": False})[0], "problem")

    def test_banners(self):
        nic = {"name": "eth0", "up": True, "addresses": ["10.0.0.5/24"], "stable": False}
        kinds = viewmodel.banners({**BASE, "other_dhcp": ["dnsmasq"], "nics": [nic], "config_state": "unsupported"})
        self.assertEqual([k for k, _t in kinds], ["warn", "info", "warn"])
        self.assertIn("dnsmasq", kinds[0][1])
        self.assertEqual(viewmodel.banners({**BASE, "kea_installed": False, "other_dhcp": ["x"]}), [])

    def test_nic_badges_do_not_rely_on_color_alone(self):
        up = {"name": "eth1", "up": True, "addresses": ["192.168.50.1/24"], "stable": True}
        self.assertEqual(viewmodel.nic_badge(up), ("ok", i18n.translate("nic_stable")))
        self.assertEqual(viewmodel.nic_badge({**up, "stable": False})[0], "warn")
        self.assertEqual(viewmodel.nic_badge({**up, "addresses": []})[0], "muted")
        self.assertEqual(viewmodel.nic_badge({**up, "up": False})[1], i18n.translate("nic_down"))

    def test_field_for_path_and_usage_class(self):
        self.assertEqual(viewmodel.field_for_path("subnets[0].pool_end"), "pool")
        self.assertEqual(viewmodel.field_for_path("subnets[0].dns[2]"), "dns")
        self.assertIsNone(viewmodel.field_for_path("subnets[0].reservations[1].ip"))
        self.assertEqual([viewmodel.usage_class(p) for p in (10, 80, 99)], ["", "high", "full"])


if __name__ == "__main__":
    unittest.main()
