import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk  # noqa: E402

from ..core import protocol, suggest  # noqa: E402
from ..core.model import ID_TYPES, ValidationError, normalize_identifier  # noqa: E402
from ..i18n import translate as _  # noqa: E402
from . import formlogic  # noqa: E402
from .helper_client import HelperError  # noqa: E402

FIELDS = ("interface", "server_ip", "subnet", "pool", "lifetime", "gateway", "dns", "domain",
          "next_server", "boot_file")


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
        self.inv = None
        self.unlocked = False
        self.set_default_size(820, 560)
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin=10)
        self.add(outer)
        self.notebook = Gtk.Notebook()
        outer.pack_start(self.notebook, True, True, 0)
        self.message = Gtk.Label(xalign=0, wrap=True, selectable=True)
        outer.pack_start(self.message, False, False, 0)
        self._build_status()
        self._build_subnet()
        self._build_reservations()
        self._build_monitor()
        self.refresh()

    # -- construction ----------------------------------------------------
    def _page(self, title):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8, margin=10)
        self.notebook.append_page(box, Gtk.Label(label=_(title)))
        return box

    def _button(self, key, handler, box):
        b = Gtk.Button(label=_(key))
        b.connect("clicked", lambda *_a: handler())
        box.pack_start(b, False, False, 0)
        return b

    def _build_status(self):
        page = self._page("tab_status")
        self.status = Gtk.Label(xalign=0, wrap=True, selectable=True)
        page.pack_start(self.status, False, False, 0)
        self.nics = Gtk.Label(xalign=0, yalign=0, selectable=True)
        page.pack_start(Gtk.Label(label=_("nics_title"), xalign=0), False, False, 0)
        page.pack_start(self.nics, True, True, 0)
        row = Gtk.Box(spacing=6)
        page.pack_start(row, False, False, 0)
        self._button("refresh", self.refresh, row)
        self.unlock_btn = self._button("btn_unlock", self.on_unlock, row)
        self.start_btn = self._button("btn_start", self.on_start, row)
        self.stop_btn = self._button("btn_stop", self.on_stop, row)

    def _build_subnet(self):
        page = self._page("tab_subnet")
        grid = Gtk.Grid(row_spacing=6, column_spacing=10)
        page.pack_start(grid, False, False, 0)
        self.entries = {}
        labels = {"interface": "f_interface", "server_ip": "f_server_ip", "subnet": "f_subnet", "pool": "f_pool",
                  "lifetime": "f_lifetime", "gateway": "f_gateway", "dns": "f_dns", "domain": "f_domain",
                  "next_server": "f_next_server", "boot_file": "f_boot_file"}
        for row, name in enumerate(FIELDS):
            grid.attach(Gtk.Label(label=_(labels[name]), xalign=0), 0, row, 1, 1)
            if name == "interface":
                widget = Gtk.ComboBoxText.new_with_entry()
                widget.connect("changed", lambda *_a: self.on_interface_changed())
                self.entries[name] = widget
            else:
                widget = Gtk.Entry(hexpand=True)
                self.entries[name] = widget
            grid.attach(widget, 1, row, 1, 1)
        self.lease_cmds = Gtk.CheckButton(label=_("opt_lease_cmds"))
        page.pack_start(self.lease_cmds, False, False, 0)
        row = Gtk.Box(spacing=6)
        page.pack_start(row, False, False, 0)
        self._button("f_suggest", self.on_interface_changed, row)
        self._button("btn_preview", self.on_preview, row)
        self._button("btn_apply", self.on_apply, row)

    def _build_reservations(self):
        page = self._page("tab_reservations")
        self.res_store = Gtk.ListStore(str, str, str, str)
        view = Gtk.TreeView(model=self.res_store)
        for i, key in enumerate(("col_type", "col_identifier", "col_ip", "col_hostname")):
            view.append_column(Gtk.TreeViewColumn(_(key), Gtk.CellRendererText(), text=i))
        self.res_view = view
        page.pack_start(view, True, True, 0)
        row = Gtk.Box(spacing=6)
        page.pack_start(row, False, False, 0)
        self.res_type = Gtk.ComboBoxText()
        for t in ID_TYPES:
            self.res_type.append_text(t)
        self.res_type.set_active(0)
        self.res_id, self.res_ip, self.res_host = (Gtk.Entry(placeholder_text=_(k)) for k in
                                                   ("col_identifier", "col_ip", "col_hostname"))
        for w in (self.res_type, self.res_id, self.res_ip, self.res_host):
            row.pack_start(w, True, True, 0)
        self._button("btn_add", self.on_add_reservation, row)
        self._button("btn_remove", self.on_remove_reservation, row)

    def _build_monitor(self):
        page = self._page("tab_monitor")
        self.pools = Gtk.Label(xalign=0, selectable=True)
        page.pack_start(self.pools, False, False, 0)
        self.leases = Gtk.Label(xalign=0, yalign=0, selectable=True)
        page.pack_start(self.leases, True, True, 0)
        self._button("refresh", self.refresh_monitor, page)

    # -- helpers ---------------------------------------------------------
    def say(self, text):
        self.message.set_text(text)

    def fail(self, exc):
        self.say(formlogic.error_message(exc.code, exc.detail))

    def confirm(self, title, body):
        dialog = Gtk.MessageDialog(transient_for=self, message_type=Gtk.MessageType.QUESTION,
                                   buttons=Gtk.ButtonsType.OK_CANCEL, text=title)
        dialog.format_secondary_text(body)
        answer = dialog.run() == Gtk.ResponseType.OK
        dialog.destroy()
        return answer

    def values(self):
        out = {}
        for name, widget in self.entries.items():
            out[name] = widget.get_active_text() if name == "interface" else widget.get_text()
        return out or {}

    def reservations(self):
        return [tuple(row) for row in self.res_store]

    def current_model(self):
        return formlogic.form_to_model(self.values(), self.reservations(), self.lease_cmds.get_active())

    def load_model(self, config):
        values, res, hook = formlogic.model_to_form(config)
        for name, widget in self.entries.items():
            if name == "interface":
                widget.get_child().set_text(values[name])
            else:
                widget.set_text(values[name])
        self.res_store.clear()
        for row in res:
            self.res_store.append(list(row))
        self.lease_cmds.set_active(hook)

    # -- actions ---------------------------------------------------------
    def refresh(self):
        try:
            self.inv = self.helper.call("inventory_private" if self.unlocked else "inventory")
        except HelperError as exc:
            if not self.unlocked:
                self.status.set_text(_("helper_error"))
                return
            self.unlocked = False
            self.fail(exc)
            try:
                self.inv = self.helper.call("inventory")
            except HelperError:
                self.status.set_text(_("helper_error"))
                return
        self.status.set_text("\n".join(summary_lines(self.inv)))
        self.nics.set_text("\n".join(describe_nic(n) for n in self.inv["nics"]))
        combo = self.entries["interface"]
        combo.remove_all()
        for nic in self.inv["nics"]:
            if nic["up"] and nic["addresses"]:
                combo.append_text(nic["name"])
        editable = self.unlocked and self.inv["config_state"] in ("pristine", "managed", "importable")
        managed = self.unlocked and self.inv["config_state"] == "managed"
        self.unlock_btn.set_sensitive(self.inv["kea_installed"] and not self.unlocked)
        self.start_btn.set_sensitive(managed)
        self.stop_btn.set_sensitive(managed)
        self.notebook.get_nth_page(1).set_sensitive(editable)
        self.notebook.get_nth_page(2).set_sensitive(editable)
        if self.unlocked:
            try:
                cur = self.helper.call("current")
                if cur.get("model"):
                    self.load_model(protocol.model_from_dict(cur["model"]))
            except HelperError as exc:
                self.fail(exc)

    def on_unlock(self):
        self.unlocked = True
        self.refresh()

    def on_interface_changed(self):
        name = self.entries["interface"].get_active_text() or ""
        nic = next((n for n in (self.inv or {}).get("nics", []) if n["name"] == name), None)
        if not nic or not nic["addresses"]:
            return
        try:
            s = suggest.suggest(nic["addresses"][0], self.entries["gateway"].get_text().strip())
        except ValueError:
            return
        self.entries["server_ip"].set_text(s.server_ip)
        self.entries["subnet"].set_text(s.subnet)
        self.entries["pool"].set_text(f"{s.pool_start} - {s.pool_end}")
        if not self.entries["lifetime"].get_text():
            self.entries["lifetime"].set_text("3600")

    def on_preview(self):
        try:
            data = self.helper.call("preview", self.current_model())
        except HelperError as exc:
            return self.fail(exc)
        dialog = Gtk.Dialog(title=_("btn_preview"), transient_for=self)
        dialog.set_default_size(640, 480)
        text = Gtk.TextView(editable=False, monospace=True)
        text.get_buffer().set_text(data["json"])
        scroll = Gtk.ScrolledWindow()
        scroll.add(text)
        dialog.get_content_area().pack_start(scroll, True, True, 0)
        dialog.add_button("OK", Gtk.ResponseType.OK)
        dialog.show_all()
        dialog.run()
        dialog.destroy()

    def on_apply(self):
        try:
            config = self.current_model()
            self.helper.call("verify", config)
        except HelperError as exc:
            return self.fail(exc)
        body = _("confirm_restart")
        if self.inv and self.inv["config_state"] == "importable":
            body += "\n" + _("confirm_adopt")
        if not self.confirm(_("confirm_apply_title"), body):
            return
        try:
            res = self.helper.call("apply", config, token=self.inv["token"])
        except HelperError as exc:
            self.fail(exc)
            return self.refresh()
        self.say(_("applied", action=res["action"]))
        self.refresh()

    def on_start(self):
        if self.confirm(_("confirm_start_title"), _("confirm_start_body")):
            try:
                self.helper.call("service_start")
            except HelperError as exc:
                return self.fail(exc)
            self.refresh()

    def on_stop(self):
        if self.confirm(_("confirm_stop_title"), ""):
            try:
                self.helper.call("service_stop")
            except HelperError as exc:
                return self.fail(exc)
            self.refresh()

    def on_add_reservation(self):
        id_type = self.res_type.get_active_text()
        try:
            ident = normalize_identifier(id_type, self.res_id.get_text())
        except ValidationError as exc:
            return self.say(formlogic.error_message("validation", f"{exc.code}|{exc.path}"))
        self.res_store.append([id_type, ident, self.res_ip.get_text().strip(), self.res_host.get_text().strip()])
        for w in (self.res_id, self.res_ip, self.res_host):
            w.set_text("")

    def on_remove_reservation(self):
        _model, it = self.res_view.get_selection().get_selected()
        if it:
            self.res_store.remove(it)

    def refresh_monitor(self):
        try:
            stats = self.helper.call("stats")
        except HelperError as exc:
            self.pools.set_text(formlogic.error_message(exc.code, exc.detail))
            return
        self.pools.set_text("\n".join(
            f"#{s['subnet_id']}: {s['assigned']}/{s['total']} ({s['percent']}%)" for s in stats["subnets"]))
        try:
            data = self.helper.call("leases", limit=200)
            self.leases.set_text("\n".join(f"{l['ip']}  {l['hw']}  {l['hostname']}" for l in data["leases"]))
        except HelperError:
            self.leases.set_text(_("monitor_no_hook"))
