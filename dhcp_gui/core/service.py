"""Explicit start/stop of the Kea service, statistics and lease pages."""
from __future__ import annotations

import ipaddress

from . import inventory, kea_ctl
from .apply import UNIT, ApplyError, SystemOps
from .paths import Paths


def _managed(paths, runner):
    inv = inventory.collect(paths, runner)
    if not inv.kea_installed:
        raise ApplyError("kea_missing")
    if inv.config_state != "managed":
        # Never touch an instance the app does not own.
        raise ApplyError("not_managed", inv.config_state)
    return inv


def start(paths: Paths, ops: SystemOps, runner=inventory.run) -> dict:
    inv = _managed(paths, runner)
    if not ops.systemctl("daemon-reload") or not ops.systemctl("enable", "--now", UNIT):
        raise ApplyError("apply_failed", "systemd could not start the unit")
    if not ops.is_active():
        raise ApplyError("apply_failed", "unit is not active after start")
    return {"active": True, "other_dhcp": inv.other_dhcp}


def stop(paths: Paths, ops: SystemOps, runner=inventory.run) -> dict:
    _managed(paths, runner)
    if not ops.systemctl("disable", "--now", UNIT):
        raise ApplyError("apply_failed", "systemd could not stop the unit")
    return {"active": ops.is_active()}


def stats(ctl=kea_ctl.send) -> dict:
    answer = ctl("statistic-get-all")
    if not answer or answer[0].get("result") != 0:
        raise ApplyError("unavailable", "Kea control socket not available")
    args = answer[0].get("arguments", {})
    subnets: dict[int, dict] = {}
    for name, series in args.items():
        if not name.startswith("subnet[") or not series:
            continue
        sid, _, metric = name[len("subnet["):].partition("].")
        if not sid.isdigit() or "pool[" in metric:
            continue
        value = series[0][0] if isinstance(series[0], list) else series[0]
        subnets.setdefault(int(sid), {})[metric] = value
    out = []
    for sid in sorted(subnets):
        m = subnets[sid]
        total, used = int(m.get("total-addresses", 0)), int(m.get("assigned-addresses", 0))
        out.append({"subnet_id": sid, "total": total, "assigned": used, "declined": int(m.get("declined-addresses", 0)),
                    "percent": round(100 * used / total, 1) if total else 0.0})
    return {"subnets": out}


def leases(from_ip: str = "start", limit: int = 100, ctl=kea_ctl.send) -> dict:
    caps = ctl("list-commands")
    commands = (caps[0].get("arguments") if caps else None) or []
    if "lease4-get-page" not in commands:
        raise ApplyError("unavailable", "lease4-get-page is not available: enable the lease_cmds hook")
    if from_ip != "start":
        try:
            ipaddress.IPv4Address(from_ip)
        except ValueError:
            raise ApplyError("validation", "bad from_ip") from None
    answer = ctl("lease4-get-page", {"from": from_ip, "limit": limit})
    if not answer or answer[0].get("result") not in (0, 3):
        raise ApplyError("unavailable", "lease query failed")
    items = (answer[0].get("arguments") or {}).get("leases", [])
    rows = [{"ip": l.get("ip-address", ""), "hw": l.get("hw-address", ""), "hostname": l.get("hostname", ""),
             "subnet_id": l.get("subnet-id", 0), "expire": l.get("cltt", 0) + l.get("valid-lft", 0), "state": l.get("state", 0)}
            for l in items[:limit]]
    return {"leases": rows, "next": rows[-1]["ip"] if len(rows) == limit else ""}
