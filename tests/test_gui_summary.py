import unittest

from dhcp_gui import i18n
from dhcp_gui.core import model, protocol
from dhcp_gui.gui import viewmodel

try:
    import gi
    gi.require_version("Gtk", "3.0")
    gi.require_version("Gdk", "3.0")
    from gi.repository import Gdk, GLib
    from dhcp_gui.gui import window
except (ImportError, ValueError):  # pragma: no cover
    Gdk = GLib = window = None

BASE = {"kea_installed": True, "kea_version": "2.6.3", "service_active": "inactive",
        "service_enabled": "enabled", "nics": [], "other_dhcp": [], "config_state": "pristine",
        "reasons": [], "writable": True, "token": "x"}


class ViewModelTest(unittest.TestCase):
    def test_every_state_has_a_message_in_both_languages(self):
        for state in ("pristine", "managed", "managed_modified", "importable", "unsupported", "unreadable"):
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


def settle(gui, timeout=5.0):
    """Let the worker threads finish and run their callbacks on the main loop."""
    import time
    end = time.time() + timeout
    ctx = GLib.MainContext.default()
    time.sleep(0.05)
    while time.time() < end and (gui.busy or ctx.pending()):
        while ctx.pending():
            ctx.iteration(False)
        time.sleep(0.02)


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
                if op in ("stats", "leases"):
                    raise window.HelperError("unavailable", "x")
                raise AssertionError(op)

        helper = Helper()
        gui = window.MainWindow(helper)
        try:
            settle(gui)
            self.assertFalse(gui.notebook.get_nth_page(1).get_sensitive())
            self.assertTrue(gui.unlock_btn.get_sensitive())
            self.assertNotIn("current", helper.calls)
            gui.on_unlock()
            settle(gui)
            self.assertTrue(gui.notebook.get_nth_page(1).get_sensitive())
            self.assertFalse(gui.unlock_btn.get_visible())
            self.assertIn("inventory_private", helper.calls)
            self.assertIn("current", helper.calls)
        finally:
            gui.destroy()


@unittest.skipIf(window is None or Gdk is None or Gdk.Display.get_default() is None, "display not available")
class ExistingConfigurationTest(unittest.TestCase):
    def _open(self, subnets):
        class Helper:
            def call(self, op, *args, **kwargs):
                if op == "inventory":
                    return {**BASE, "config_state": "unreadable", "writable": False}
                if op == "inventory_private":
                    return {**BASE, "config_state": "managed"}
                if op == "current":
                    return {"model": protocol.model_to_dict(model.DhcpConfig(subnets))}
                if op in ("stats", "leases"):
                    raise window.HelperError("unavailable", "x")
                raise AssertionError(op)

        gui = window.MainWindow(Helper())
        settle(gui)
        gui.on_unlock()
        settle(gui)
        return gui

    def test_multiple_subnets_cannot_be_edited_in_single_subnet_form(self):
        first = model.Subnet(3, "eth1", "192.168.50.1", "192.168.50.0/24",
                             "192.168.50.100", "192.168.50.200")
        second = model.Subnet(4, "eth2", "192.168.60.1", "192.168.60.0/24",
                              "192.168.60.100", "192.168.60.200")
        gui = self._open([first, second])
        try:
            self.assertFalse(gui.notebook.get_nth_page(1).get_sensitive())
            self.assertFalse(gui.notebook.get_nth_page(2).get_sensitive())
            self.assertIsNone(gui.validate_form())
        finally:
            gui.destroy()

    def test_existing_subnet_id_survives_form_edit(self):
        sub = model.Subnet(7, "eth1", "192.168.50.1", "192.168.50.0/24",
                           "192.168.50.100", "192.168.50.200")
        gui = self._open([sub])
        try:
            self.assertEqual(gui.current_model().subnets[0].id, 7)
        finally:
            gui.destroy()


if __name__ == "__main__":
    unittest.main()
