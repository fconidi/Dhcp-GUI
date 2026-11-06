"""Display decisions that do not need GTK (so they are testable without a display)."""
from __future__ import annotations

from ..i18n import translate as _

FIELD_BY_PATH = {"interface": "interface", "server_ip": "server_ip", "subnet": "subnet", "pool_start": "pool",
                 "pool_end": "pool", "valid_lifetime": "lifetime", "gateway": "gateway", "dns": "dns",
                 "domain": "domain", "next_server": "next_server", "boot_file": "boot_file"}


def field_for_path(path: str) -> str | None:
    """Map a model path such as 'subnets[0].pool_end' to the form field to highlight."""
    last = path.rsplit(".", 1)[-1].split("[", 1)[0]
    if "reservations" in path:
        return None
    return FIELD_BY_PATH.get(last)


def service_state(inv: dict) -> tuple[str, str, str]:
    """(css class of the dot, title, detail line) for the top band."""
    if not inv["kea_installed"]:
        return "problem", _("svc_nokea"), _("kea_missing")
    active = inv["service_active"]
    state = "running" if active == "active" else ("stopped" if active in ("inactive", "failed") else "problem")
    title = {"running": _("svc_running"), "stopped": _("svc_stopped"), "problem": _("svc_unknown")}[state]
    detail = _("svc_detail", version=inv["kea_version"], enabled=inv["service_enabled"])
    return state, title, detail + "  ·  " + _("state_" + inv["config_state"])


def banners(inv: dict) -> list[tuple[str, str]]:
    """List of (kind, text): 'warn' or 'info'."""
    out = []
    if not inv["kea_installed"]:
        return out
    if inv["other_dhcp"]:
        out.append(("warn", _("other_dhcp", names=", ".join(inv["other_dhcp"]))))
    if inv["config_state"] in ("managed_modified", "unsupported"):
        out.append(("info", _("banner_readonly")))
    for nic in inv["nics"]:
        if nic["up"] and nic["addresses"] and not nic["stable"]:
            out.append(("warn", _("banner_dynamic", nic=nic["name"])))
            break
    return out


def nic_badge(nic: dict) -> tuple[str, str]:
    """(css class, text) for an interface row."""
    if not nic["up"]:
        return "muted", _("nic_down")
    if not nic["addresses"]:
        return "muted", _("nic_no_address")
    return ("ok", _("nic_stable")) if nic["stable"] else ("warn", _("nic_dynamic"))


def usage_class(percent: float) -> str:
    return "full" if percent >= 95 else ("high" if percent >= 80 else "")
