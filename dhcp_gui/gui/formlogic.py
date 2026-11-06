"""GUI-independent form logic (testable without a display)."""
from __future__ import annotations

from ..core.model import DhcpConfig, Reservation, Subnet
from ..i18n import translate as _


def parse_pool(text: str) -> tuple[str, str]:
    parts = [p.strip() for p in text.replace("–", "-").split("-")]
    if len(parts) != 2 or not all(parts):
        return text.strip(), ""
    return parts[0], parts[1]


def form_to_model(values: dict, reservations: list[tuple], lease_cmds: bool, subnet_id: int = 1) -> DhcpConfig:
    start, end = parse_pool(values["pool"])
    try:
        lifetime = int(values["lifetime"])
    except ValueError:
        lifetime = 0
    sub = Subnet(
        id=subnet_id, interface=values["interface"].strip(), server_ip=values["server_ip"].strip(),
        subnet=values["subnet"].strip(), pool_start=start, pool_end=end, valid_lifetime=lifetime,
        gateway=values["gateway"].strip(),
        dns=[d.strip() for d in values["dns"].split(",") if d.strip()],
        domain=values["domain"].strip(), next_server=values["next_server"].strip(),
        boot_file=values["boot_file"].strip(),
        reservations=[Reservation(t, i, ip, h) for t, i, ip, h in reservations])
    return DhcpConfig([sub], lease_cmds)


def model_to_form(config: DhcpConfig) -> tuple[dict, list[tuple], bool]:
    sub = config.subnets[0]
    values = {"interface": sub.interface, "server_ip": sub.server_ip, "subnet": sub.subnet,
              "pool": f"{sub.pool_start} - {sub.pool_end}", "lifetime": str(sub.valid_lifetime),
              "gateway": sub.gateway, "dns": ", ".join(sub.dns), "domain": sub.domain,
              "next_server": sub.next_server, "boot_file": sub.boot_file}
    res = [(r.id_type, r.identifier, r.ip, r.hostname) for r in sub.reservations]
    return values, res, config.lease_cmds


def error_message(code: str, detail: str = "") -> str:
    """Human message for a helper error; keeps the outcome markers readable."""
    if code == "validation":
        what, _sep, path = detail.partition("|")
        return _("err_validation", detail=what or detail, path=path)
    if code == "apply_failed" and "outcome=restore_failed" in detail:
        return _("err_restore_failed", detail=detail)
    key = {"conflict": "err_conflict", "denied": "err_denied", "not_managed": "err_not_managed",
           "kea_rejected": "err_kea_rejected", "apply_failed": "err_apply_failed",
           "unavailable": "err_unavailable"}.get(code)
    if key is None:
        return _("err_other", detail=detail or code)
    return _(key, detail=detail)
