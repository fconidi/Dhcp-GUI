import threading

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk  # noqa: E402

from ..core import protocol, suggest  # noqa: E402
from ..core.model import ID_TYPES, ValidationError, normalize_identifier  # noqa: E402
from ..i18n import translate as _  # noqa: E402
from . import formlogic, style, viewmodel  # noqa: E402
from .helper_client import HelperError  # noqa: E402

FIELDS = ("interface", "server_ip", "subnet", "pool", "lifetime", "gateway", "dns", "domain",
          "next_server", "boot_file")
LABELS = {"interface": "f_interface", "server_ip": "f_server_ip", "subnet": "f_subnet", "pool": "f_pool",
          "lifetime": "f_lifetime", "gateway": "f_gateway", "dns": "f_dns", "domain": "f_domain",
          "next_server": "f_next_server", "boot_file": "f_boot_file"}


def css(widget, *classes):
    ctx = widget.get_style_context()
    for name in classes:
        ctx.add_class(name)
    return widget


def label(text="", *classes, xalign=0.0, wrap=False, selectable=False):
    w = Gtk.Label(label=text, xalign=xalign, wrap=wrap, selectable=selectable)
    return css(w, *classes)


def button(text, handler, *classes, icon=None):
    b = Gtk.Button()
    box = Gtk.Box(spacing=6)
    if icon:
        box.pack_start(Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.BUTTON), False, False, 0)
    box.pack_start(Gtk.Label(label=text), False, False, 0)
    b.add(box)
    b.connect("clicked", lambda *_a: handler())
    return css(b, *classes)


class MainWindow(Gtk.Window):
    def __init__(self, helper):
        super().__init__(title=_("app_title"))
        style.install()
        self.helper = helper
        self.inv = None
        self.unlocked = False
        self.busy = 0
        self.set_default_size(920, 680)
        self.set_size_request(760, 560)
        root = css(Gtk.Box(orientation=Gtk.Orientation.VERTICAL), "dg-root")
        self.add(root)
        root.pack_start(self._build_band(), False, False, 0)
        self.banners = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        root.pack_start(self.banners, False, False, 0)
        self.notebook = css(Gtk.Notebook(), "dg-tabs")
        root.pack_start(self.notebook, True, True, 0)
        self.msg = css(Gtk.Box(spacing=10), "dg-msg")
        self.msg_label = label("", wrap=True, selectable=True)
        self.msg.pack_start(self.msg_label, True, True, 0)
        self.msg.pack_end(button(_("dismiss"), lambda: self.msg.hide(), "dg-quiet"), False, False, 0)
        root.pack_end(self.msg, False, False, 0)
        self._build_status()
        self._build_subnet()
        self._build_reservations()
        self._build_monitor()
        self.refresh()

    # -- construction ----------------------------------------------------
    def _build_band(self):
        band = css(Gtk.Box(spacing=14), "dg-band")
        self.dot = css(Gtk.Box(), "dg-dot")
        self.dot.set_valign(Gtk.Align.CENTER)
        band.pack_start(self.dot, False, False, 0)
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.band_title = label("", "dg-band-title")
        self.band_detail = label("", "dg-band-detail", wrap=True)
        text.pack_start(self.band_title, False, False, 0)
        text.pack_start(self.band_detail, False, False, 0)
        band.pack_start(text, True, True, 0)
        self.spinner = Gtk.Spinner()
        band.pack_end(self.spinner, False, False, 0)
        self.unlock_btn = button(_("btn_unlock"), self.on_unlock, "dg-primary", icon="changes-allow-symbolic")
        band.pack_end(self.unlock_btn, False, False, 0)
        self.service_btn = button(_("btn_start"), self.on_service, icon="media-playback-start-symbolic")
        band.pack_end(self.service_btn, False, False, 0)
        return band

    def _page(self, title):
        scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14, margin=18)
        scroll.add(box)
        self.notebook.append_page(scroll, Gtk.Label(label=_(title)))
        return box

    def _section(self, title, page):
        outer = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        outer.pack_start(label(_(title), "dg-section-title"), False, False, 0)
        body = css(Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10), "dg-section")
        outer.pack_start(body, False, False, 0)
        page.pack_start(outer, False, False, 0)
        return body

    def _build_status(self):
        page = self._page("tab_status")
        body = self._section("nics_title", page)
        self.nic_list = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        body.pack_start(self.nic_list, False, False, 0)
        self.reasons_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        page.pack_start(self.reasons_box, False, False, 0)
        row = Gtk.Box(spacing=8)
        page.pack_start(row, False, False, 0)
        row.pack_start(button(_("refresh"), self.refresh, icon="view-refresh-symbolic"), False, False, 0)

    def _field_row(self, grid, row, name, widget, hint=None):
        grid.attach(label(_(LABELS[name]), "dg-label"), 0, row * 2, 1, 1)
        grid.attach(widget, 1, row * 2, 1, 1)
        if hint:
            grid.attach(label(_(hint), "dg-hint", wrap=True), 1, row * 2 + 1, 1, 1)

    def _build_subnet(self):
        page = self._page("tab_subnet")
        self.entries = {}

        def entry(name):
            w = css(Gtk.Entry(hexpand=True, width_chars=36), "dg-field")
            w.connect("changed", lambda *_a, n=name: self._clear_error(n))
            self.entries[name] = w
            return w

        def grid_for(title):
            body = self._section(title, page)
            g = Gtk.Grid(row_spacing=4, column_spacing=16)
            body.pack_start(g, False, False, 0)
            return g

        net = grid_for("sec_network")
        combo = css(Gtk.ComboBoxText.new_with_entry(), "dg-field")
        combo.set_hexpand(True)
        combo.connect("changed", lambda *_a: self.on_interface_changed())
        self.entries["interface"] = combo
        self._field_row(net, 0, "interface", combo, "h_interface")
        self._field_row(net, 1, "server_ip", entry("server_ip"))
        self._field_row(net, 2, "subnet", entry("subnet"))
        self._field_row(net, 3, "pool", entry("pool"), "h_pool")
        opt = grid_for("sec_options")
        self._field_row(opt, 0, "lifetime", entry("lifetime"), "h_lifetime")
        self._field_row(opt, 1, "gateway", entry("gateway"), "h_gateway")
        self._field_row(opt, 2, "dns", entry("dns"), "h_dns")
        self._field_row(opt, 3, "domain", entry("domain"))
        pxe = grid_for("sec_pxe")
        self._field_row(pxe, 0, "next_server", entry("next_server"), "h_pxe")
        self._field_row(pxe, 1, "boot_file", entry("boot_file"))
        self.lease_cmds = Gtk.CheckButton(label=_("opt_lease_cmds"))
        page.pack_start(self.lease_cmds, False, False, 0)
        bar = Gtk.Box(spacing=8)
        page.pack_start(bar, False, False, 0)
        bar.pack_start(button(_("f_suggest"), self.on_interface_changed, "dg-quiet", icon="view-refresh-symbolic"),
                       False, False, 0)
        self.apply_btn = button(_("btn_apply"), self.on_apply, "dg-primary")
        bar.pack_end(self.apply_btn, False, False, 0)
        self.preview_btn = button(_("btn_preview"), self.on_preview)
        bar.pack_end(self.preview_btn, False, False, 0)
        self.subnet_widgets = [bar, net, opt, pxe, self.lease_cmds]

    def _build_reservations(self):
        page = self._page("tab_reservations")
        body = self._section("tab_reservations", page)
        self.res_store = Gtk.ListStore(str, str, str, str)
        view = css(Gtk.TreeView(model=self.res_store), "dg-list")
        for i, key in enumerate(("col_type", "col_identifier", "col_ip", "col_hostname")):
            renderer = Gtk.CellRendererText()
            if i in (1, 2):
                renderer.set_property("family", "monospace")
            col = Gtk.TreeViewColumn(_(key), renderer, text=i)
            col.set_resizable(True)
            col.set_expand(True)
            view.append_column(col)
        self.res_view = view
        self.res_stack = Gtk.Stack()
        self.res_stack.add_named(css(label(_("res_empty"), wrap=True, xalign=0.5), "dg-empty"), "empty")
        scroll = Gtk.ScrolledWindow(min_content_height=200)
        scroll.add(view)
        self.res_stack.add_named(scroll, "list")
        body.pack_start(self.res_stack, True, True, 0)
        add = Gtk.Box(spacing=8)
        body.pack_start(add, False, False, 0)
        self.res_type = Gtk.ComboBoxText()
        for t in ID_TYPES:
            self.res_type.append_text(t)
        self.res_type.set_active(0)
        self.res_id = css(Gtk.Entry(placeholder_text=_("res_id_hint"), hexpand=True), "dg-field", "dg-mono")
        self.res_ip = css(Gtk.Entry(placeholder_text=_("res_ip_hint"), hexpand=True), "dg-field", "dg-mono")
        self.res_host = css(Gtk.Entry(placeholder_text=_("col_hostname"), hexpand=True), "dg-field")
        for w in (self.res_type, self.res_id, self.res_ip, self.res_host):
            add.pack_start(w, w is not self.res_type, True, 0)
        add.pack_start(button(_("btn_add"), self.on_add_reservation, icon="list-add-symbolic"), False, False, 0)
        add.pack_start(button(_("btn_remove"), self.on_remove_reservation, "dg-danger", icon="list-remove-symbolic"),
                       False, False, 0)
        self.res_page_body = body
        self._update_res_stack()

    def _build_monitor(self):
        page = self._page("tab_monitor")
        usage = self._section("col_pool", page)
        self.usage_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=10)
        usage.pack_start(self.usage_box, False, False, 0)
        leases = self._section("tab_monitor", page)
        self.lease_store = Gtk.ListStore(str, str, str)
        view = css(Gtk.TreeView(model=self.lease_store), "dg-list")
        for i, key in enumerate(("col_ip", "col_identifier", "col_hostname")):
            renderer = Gtk.CellRendererText()
            if i < 2:
                renderer.set_property("family", "monospace")
            col = Gtk.TreeViewColumn(_(key), renderer, text=i)
            col.set_expand(True)
            view.append_column(col)
        self.lease_stack = Gtk.Stack()
        self.lease_empty = css(label("", wrap=True, xalign=0.5), "dg-empty")
        self.lease_stack.add_named(self.lease_empty, "empty")
        scroll = Gtk.ScrolledWindow(min_content_height=200)
        scroll.add(view)
        self.lease_stack.add_named(scroll, "list")
        leases.pack_start(self.lease_stack, True, True, 0)
        page.pack_start(button(_("refresh"), self.refresh_monitor, icon="view-refresh-symbolic"), False, False, 0)

    # -- helpers ---------------------------------------------------------
    def say(self, text, kind="ok"):
        ctx = self.msg.get_style_context()
        ctx.remove_class("ok")
        ctx.remove_class("error")
        ctx.add_class(kind)
        self.msg_label.set_text(text)
        self.msg.show_all()

    def fail(self, exc):
        self.say(formlogic.error_message(exc.code, exc.detail), "error")

    def set_busy(self, delta):
        self.busy += delta
        working = self.busy > 0
        (self.spinner.start if working else self.spinner.stop)()
        self.spinner.set_visible(working)
        for b in (self.service_btn, self.apply_btn, self.preview_btn):
            b.set_sensitive(not working and getattr(b, "_wanted", True))

    def run_async(self, work, done, failed=None, hint=True):
        """Run `work` (blocking helper calls) in a thread; update the UI from the main loop."""
        self.set_busy(1)
        if hint:
            self.msg.hide()

        def thread():
            try:
                result = work()
            except HelperError as exc:
                GLib.idle_add(finish, None, exc)
                return
            GLib.idle_add(finish, result, None)

        def finish(result, exc):
            self.set_busy(-1)
            if exc is not None:
                (failed or self.fail)(exc)
            else:
                done(result)
            return False

        threading.Thread(target=thread, daemon=True).start()

    def confirm(self, title, body):
        dialog = Gtk.MessageDialog(transient_for=self, message_type=Gtk.MessageType.QUESTION,
                                   buttons=Gtk.ButtonsType.OK_CANCEL, text=title)
        if body:
            dialog.format_secondary_text(body)
        answer = dialog.run() == Gtk.ResponseType.OK
        dialog.destroy()
        return answer

    def values(self):
        out = {}
        for name, widget in self.entries.items():
            out[name] = widget.get_active_text() if name == "interface" else widget.get_text()
        return out

    def reservations(self):
        return [tuple(row) for row in self.res_store]

    def current_model(self):
        return formlogic.form_to_model(self.values(), self.reservations(), self.lease_cmds.get_active())

    def load_model(self, config):
        values, res, hook = formlogic.model_to_form(config)
        for name, widget in self.entries.items():
            (widget.get_child() if name == "interface" else widget).set_text(values[name])
        self.res_store.clear()
        for row in res:
            self.res_store.append(list(row))
        self._update_res_stack()
        self.lease_cmds.set_active(hook)

    def _clear_error(self, name):
        css_ctx = self.entries[name].get_style_context()
        css_ctx.remove_class("error")

    def _mark_error(self, name):
        if name in self.entries:
            self.entries[name].get_style_context().add_class("error")
            self.entries[name].grab_focus()

    def _update_res_stack(self):
        self.res_stack.set_visible_child_name("list" if len(self.res_store) else "empty")

    # -- rendering the inventory ---------------------------------------
    def render_inventory(self, inv):
        self.inv = inv
        state, title, detail = viewmodel.service_state(inv)
        ctx = self.dot.get_style_context()
        for c in ("running", "stopped", "problem"):
            ctx.remove_class(c)
        ctx.add_class(state)
        self.band_title.set_text(title)
        self.band_detail.set_text(detail)
        managed = self.unlocked and inv["config_state"] == "managed"
        running = state == "running"
        self.service_btn.get_child().get_children()[0].set_from_icon_name(
            "media-playback-stop-symbolic" if running else "media-playback-start-symbolic", Gtk.IconSize.BUTTON)
        self.service_btn.get_child().get_children()[1].set_text(_("btn_stop") if running else _("btn_start"))
        self.service_btn._wanted = managed
        self.service_btn.set_sensitive(managed and self.busy == 0)
        css(self.service_btn, "dg-danger") if running else self.service_btn.get_style_context().remove_class("dg-danger")
        for child in self.banners.get_children():
            self.banners.remove(child)
        for kind, text in viewmodel.banners(inv):
            row = css(Gtk.Box(spacing=10), "dg-banner", *(["info"] if kind == "info" else []))
            icon = "dialog-warning-symbolic" if kind == "warn" else "dialog-information-symbolic"
            row.pack_start(Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.BUTTON), False, False, 0)
            row.pack_start(label(text, wrap=True), True, True, 0)
            self.banners.pack_start(row, False, False, 0)
        self.banners.show_all()
        for child in self.nic_list.get_children():
            self.nic_list.remove(child)
        if not inv["nics"]:
            self.nic_list.pack_start(css(label(_("nic_none"), xalign=0.5), "dg-empty"), False, False, 0)
        for nic in inv["nics"]:
            row = css(Gtk.Box(spacing=12), "dg-row")
            row.pack_start(label(nic["name"], "dg-nic-name"), False, False, 0)
            row.pack_start(label(", ".join(nic["addresses"]), "dg-mono"), True, True, 0)
            kind, text = viewmodel.nic_badge(nic)
            row.pack_end(label(text, "dg-badge", kind), False, False, 0)
            self.nic_list.pack_start(row, False, False, 0)
        self.nic_list.show_all()
        for child in self.reasons_box.get_children():
            self.reasons_box.remove(child)
        if inv["reasons"]:
            self.reasons_box.pack_start(label(_("reasons_title"), "dg-section-title"), False, False, 0)
            for reason in inv["reasons"][:8]:
                self.reasons_box.pack_start(label("• " + reason, "dg-hint", wrap=True, selectable=True),
                                            False, False, 0)
        self.reasons_box.show_all()
        editable = self.unlocked and inv["kea_installed"] and inv["config_state"] in ("pristine", "managed", "importable")
        for widget in self.subnet_widgets:
            widget.set_sensitive(editable)
        self.notebook.get_nth_page(1).set_sensitive(editable)
        self.notebook.get_nth_page(2).set_sensitive(editable)
        self.unlock_btn.set_visible(inv["kea_installed"] and not self.unlocked)
        self.unlock_btn.set_sensitive(inv["kea_installed"] and not self.unlocked and self.busy == 0)
        combo = self.entries["interface"]
        combo.remove_all()
        for nic in inv["nics"]:
            if nic["up"] and nic["addresses"]:
                combo.append_text(nic["name"])

    # -- actions ---------------------------------------------------------
    def refresh(self):
        unlocked = self.unlocked

        def work():
            error = None
            try:
                inv = self.helper.call("inventory_private" if unlocked else "inventory")
            except HelperError as exc:
                if not unlocked:
                    raise
                error, unlocked_ok = exc, False
                inv = self.helper.call("inventory")
            else:
                unlocked_ok = unlocked
            cur = {}
            if unlocked_ok:
                try:
                    cur = self.helper.call("current")
                except HelperError as exc:
                    error = exc
            return inv, cur, unlocked_ok, error

        def done(result):
            inv, cur, unlocked_ok, error = result
            self.unlocked = unlocked_ok
            self.render_inventory(inv)
            if error is not None:
                self.fail(error)
            if cur.get("model"):
                self.load_model(protocol.model_from_dict(cur["model"]))
            self.refresh_monitor()

        self.run_async(work, done, lambda exc: self.say(_("helper_error"), "error"), hint=False)

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

    def validate_form(self):
        """Validate locally (no password needed); highlight the offending field."""
        try:
            config = self.current_model()
            from ..core import model as m
            m.validate(config)
            return config
        except ValidationError as exc:
            self._mark_error(viewmodel.field_for_path(exc.path) or "")
            self.say(formlogic.error_message("validation", f"{exc.code}|{exc.path}"), "error")
            return None

    def on_preview(self):
        config = self.validate_form()
        if config is None:
            return

        def done(data):
            dialog = Gtk.Dialog(title=_("btn_preview"), transient_for=self)
            dialog.set_default_size(680, 520)
            text = Gtk.TextView(editable=False, monospace=True, left_margin=10, top_margin=8)
            text.get_buffer().set_text(data["json"])
            scroll = Gtk.ScrolledWindow()
            scroll.add(text)
            dialog.get_content_area().pack_start(scroll, True, True, 0)
            dialog.add_button("OK", Gtk.ResponseType.OK)
            dialog.show_all()
            dialog.run()
            dialog.destroy()

        self.run_async(lambda: self.helper.call("preview", config), done)

    def on_apply(self):
        config = self.validate_form()
        if config is None:
            return
        body = _("confirm_restart")
        if self.inv and self.inv["config_state"] == "importable":
            body += "\n" + _("confirm_adopt")
        if not self.confirm(_("confirm_apply_title"), body):
            return

        def done(res):
            self.say(_("applied", action=res["action"]), "ok")
            self.refresh()

        def failed(exc):
            self.fail(exc)
            self.refresh()

        self.run_async(lambda: self.helper.call("apply", config, token=self.inv["token"]), done, failed)

    def on_service(self):
        running = self.inv and self.inv["service_active"] == "active"
        if running:
            if not self.confirm(_("confirm_stop_title"), ""):
                return
            op = "service_stop"
        else:
            if not self.confirm(_("confirm_start_title"), _("confirm_start_body")):
                return
            op = "service_start"
        self.run_async(lambda: self.helper.call(op), lambda _r: self.refresh())

    def on_add_reservation(self):
        id_type = self.res_type.get_active_text()
        try:
            ident = normalize_identifier(id_type, self.res_id.get_text())
        except ValidationError as exc:
            return self.say(formlogic.error_message("validation", f"{exc.code}|{exc.path}"), "error")
        self.res_store.append([id_type, ident, self.res_ip.get_text().strip(), self.res_host.get_text().strip()])
        for w in (self.res_id, self.res_ip, self.res_host):
            w.set_text("")
        self._update_res_stack()

    def on_remove_reservation(self):
        _model, it = self.res_view.get_selection().get_selected()
        if it:
            self.res_store.remove(it)
        self._update_res_stack()

    def refresh_monitor(self):
        def clear_usage():
            for child in self.usage_box.get_children():
                self.usage_box.remove(child)

        if not self.inv or self.inv["service_active"] != "active":
            clear_usage()
            self.usage_box.pack_start(css(label(_("mon_stopped"), wrap=True, xalign=0.5), "dg-empty"),
                                      False, False, 0)
            self.usage_box.show_all()
            self.lease_store.clear()
            self.lease_empty.set_text(_("mon_stopped"))
            self.lease_stack.set_visible_child_name("empty")
            return

        def work():
            stats = self.helper.call("stats")
            try:
                leases = self.helper.call("leases", limit=200)
            except HelperError:
                leases = None
            return stats, leases

        def done(result):
            stats, leases = result
            clear_usage()
            for s in stats["subnets"]:
                row = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
                head = Gtk.Box(spacing=8)
                head.pack_start(label(_("mon_subnet", id=s["subnet_id"]), "dg-nic-name"), False, False, 0)
                head.pack_end(label(f"{s['percent']}%", "dg-mono"), False, False, 0)
                bar = css(Gtk.LevelBar(min_value=0, max_value=100, value=min(s["percent"], 100)), "dg-usage")
                bar.add_offset_value("high", 79.9)
                bar.add_offset_value("full", 94.9)
                bar.add_offset_value("low", 0)
                row.pack_start(head, False, False, 0)
                row.pack_start(bar, False, False, 0)
                row.pack_start(label(_("mon_usage", used=s["assigned"], total=s["total"]), "dg-hint"), False, False, 0)
                self.usage_box.pack_start(row, False, False, 0)
            self.usage_box.show_all()
            self.lease_store.clear()
            if leases is None:
                self.lease_empty.set_text(_("monitor_no_hook"))
                self.lease_stack.set_visible_child_name("empty")
                return
            for l in leases["leases"]:
                self.lease_store.append([l["ip"], l["hw"], l["hostname"]])
            self.lease_empty.set_text(_("mon_no_leases"))
            self.lease_stack.set_visible_child_name("list" if len(self.lease_store) else "empty")

        def failed(exc):
            clear_usage()
            self.usage_box.pack_start(label(formlogic.error_message(exc.code, exc.detail), "dg-hint", wrap=True),
                                      False, False, 0)
            self.usage_box.show_all()

        self.run_async(work, done, failed, hint=False)
