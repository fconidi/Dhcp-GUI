import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gtk  # noqa: E402

from ..i18n import translate as _  # noqa: E402
from .helper_client import HelperError  # noqa: E402


def describe_nic(nic: dict) -> str:
    if not nic["up"]:
        note = _("nic_down")
    elif not nic["addresses"]:
        note = _("nic_no_address")
    else:
        note = _("nic_stable") if nic["stable"] else _("nic_dynamic")
    addresses = ", ".join(nic["addresses"])
    return f"{nic['name']}  {addresses}  ({note})".replace("  ()", "")


def summary_lines(inv: dict) -> list[str]:
    """Plain-text summary of an inventory, shared by the window and tests."""
    if not inv["kea_installed"]:
        return [_("kea_missing")]
    lines = [_("kea_version", version=inv["kea_version"]),
             _("service_state", active=inv["service_active"], enabled=inv["service_enabled"]),
             _("state_" + inv["config_state"])]
    lines += [f"  - {reason}" for reason in inv["reasons"][:6]]
    if inv["other_dhcp"]:
        lines.append(_("other_dhcp", names=", ".join(inv["other_dhcp"])))
    return lines


class MainWindow(Gtk.Window):
    def __init__(self, helper):
        super().__init__(title=_("app_title"))
        self.helper = helper
        self.set_default_size(720, 480)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin=12)
        self.add(box)
        self.status = Gtk.Label(xalign=0, wrap=True, selectable=True)
        box.pack_start(self.status, False, False, 0)
        box.pack_start(Gtk.Label(label=_("nics_title"), xalign=0), False, False, 0)
        self.nics = Gtk.Label(xalign=0, yalign=0, selectable=True)
        scroll = Gtk.ScrolledWindow()
        scroll.add(self.nics)
        box.pack_start(scroll, True, True, 0)
        button = Gtk.Button(label=_("refresh"))
        button.connect("clicked", lambda *_a: self.refresh())
        box.pack_start(button, False, False, 0)
        self.refresh()

    def refresh(self):
        try:
            inv = self.helper.call("inventory")
        except HelperError:
            self.status.set_text(_("helper_error"))
            return
        self.status.set_text("\n".join(summary_lines(inv)))
        self.nics.set_text("\n".join(describe_nic(n) for n in inv["nics"]))
