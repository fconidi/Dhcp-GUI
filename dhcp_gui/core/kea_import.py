"""Lossless import of a Kea DHCPv4 configuration into the app model.

Only a documented subset is accepted. Every key must be consumed by the
importer; anything left over makes the file unsupported (read-only for the app).
"""
from __future__ import annotations

import json

from .model import (CONTROL_SOCKET, HOOK_LEASE_CMDS, LEASE_FILE, DhcpConfig, Reservation, Subnet,
                    ValidationError, validate)


class Unsupported(Exception):
    def __init__(self, reasons):
        super().__init__("; ".join(reasons))
        self.reasons = list(reasons)


def strip_comments(text: str) -> str:
    """Remove //, # and /* */ comments outside of strings."""
    out, i, n = [], 0, len(text)
    while i < n:
        ch = text[i]
        if ch == '"':
            j = i + 1
            while j < n and text[j] != '"':
                j += 2 if text[j] == "\\" else 1
            out.append(text[i:j + 1])
            i = j + 1
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            if end < 0:
                raise Unsupported(["unterminated comment"])
            out.append(" ")
            i = end + 2
        elif text.startswith("//", i) or ch == "#":
            end = text.find("\n", i)
            i = n if end < 0 else end
        else:
            out.append(ch)
            i += 1
    return _drop_trailing_commas("".join(out))


def _drop_trailing_commas(text: str) -> str:
    """Kea tolerates a comma before a closing brace or bracket; JSON does not."""
    out, i, n = [], 0, len(text)
    while i < n:
        ch = text[i]
        if ch == '"':
            j = i + 1
            while j < n and text[j] != '"':
                j += 2 if text[j] == "\\" else 1
            out.append(text[i:j + 1])
            i = j + 1
        elif ch == ",":
            j = i + 1
            while j < n and text[j] in " \t\r\n":
                j += 1
            if j < n and text[j] in "}]":
                i += 1
                continue
            out.append(ch)
            i += 1
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def parse_text(text: str) -> dict:
    if "<?include" in text:
        raise Unsupported(["file uses <?include?>"])
    try:
        return json.loads(strip_comments(text))
    except ValueError as exc:
        raise Unsupported([f"not valid Kea JSON: {str(exc)[:80]}"]) from None


class _Taker:
    def __init__(self, data, name, reasons):
        self.data, self.name, self.reasons = dict(data), name, reasons

    def take(self, key, default=None):
        return self.data.pop(key, default)

    def require_equal(self, key, expected):
        if key in self.data:
            value = self.data.pop(key)
            if value != expected:
                self.reasons.append(f"{self.name}.{key} differs from the managed value")

    def leftovers(self):
        for key in sorted(self.data):
            self.reasons.append(f"unsupported key {self.name}.{key}")


_ROUTERS, _DNS, _DOMAIN = "routers", "domain-name-servers", "domain-name"


def _subnet(raw, index, default_lifetime, reasons) -> Subnet | None:
    t = _Taker(raw, f"subnet4[{index}]", reasons)
    pools = t.take("pools", [])
    if len(pools) != 1 or not isinstance(pools[0], dict) or set(pools[0]) - {"pool"}:
        reasons.append(f"subnet4[{index}] needs exactly one plain pool")
        pools = [{"pool": " - "}]
    try:
        start, end = [x.strip() for x in pools[0]["pool"].split("-")]
    except (KeyError, ValueError, AttributeError):
        reasons.append(f"subnet4[{index}] pool is not 'start - end'")
        start = end = ""
    opts = {"routers": "", "dns": [], "domain": ""}
    for opt in t.take("option-data", []):
        name = opt.get("name") if isinstance(opt, dict) else None
        if not isinstance(opt, dict) or set(opt) - {"name", "data"} or name not in (_ROUTERS, _DNS, _DOMAIN):
            reasons.append(f"subnet4[{index}] option not supported: {str(name)[:40]}")
        elif name == _ROUTERS:
            opts["routers"] = str(opt.get("data", ""))
        elif name == _DNS:
            opts["dns"] = [x.strip() for x in str(opt.get("data", "")).split(",") if x.strip()]
        else:
            opts["domain"] = str(opt.get("data", ""))
    res = []
    for r in t.take("reservations", []):
        if not isinstance(r, dict):
            reasons.append(f"subnet4[{index}] reservation is not an object")
            continue
        rt = _Taker(r, f"subnet4[{index}].reservations", reasons)
        id_type = next((k for k in ("hw-address", "client-id") if k in rt.data), None)
        if id_type is None:
            reasons.append(f"subnet4[{index}] reservation without hw-address/client-id")
            continue
        res.append(Reservation(id_type, str(rt.take(id_type)), str(rt.take("ip-address", "")),
                               str(rt.take("hostname", ""))))
        rt.leftovers()
    sub = Subnet(
        id=t.take("id", 0), interface=str(t.take("interface", "")), server_ip="",
        subnet=str(t.take("subnet", "")), pool_start=start, pool_end=end,
        valid_lifetime=t.take("valid-lifetime", default_lifetime),
        gateway=opts["routers"], dns=opts["dns"], domain=opts["domain"],
        next_server=str(t.take("next-server", "")), boot_file=str(t.take("boot-file-name", "")),
        reservations=res)
    t.leftovers()
    return sub


def import_config(text: str) -> DhcpConfig:
    """Return a model equivalent to the file, or raise Unsupported with every reason."""
    data = parse_text(text)
    reasons: list[str] = []
    if not isinstance(data, dict) or set(data) != {"Dhcp4"} or not isinstance(data["Dhcp4"], dict):
        raise Unsupported(["top level must be exactly {\"Dhcp4\": {...}}"])
    t = _Taker(data["Dhcp4"], "Dhcp4", reasons)
    ic = _Taker(t.take("interfaces-config", {}), "interfaces-config", reasons)
    interfaces = ic.take("interfaces", [])
    for key in ("service-sockets-require-all", "service-sockets-max-retries", "service-sockets-retry-wait-time"):
        ic.take(key)  # tuning that the generator always rewrites
    ic.leftovers()
    cs = t.take("control-socket")
    if cs is not None and cs not in ({"socket-type": "unix", "socket-name": CONTROL_SOCKET},
                                     {"socket-type": "unix", "socket-name": "kea4-ctrl-socket"}):
        reasons.append("control-socket differs from the managed value")
    ld = _Taker(t.take("lease-database", {}), "lease-database", reasons)
    if ld.take("type") != "memfile":
        reasons.append("lease-database must be memfile")
    name = ld.take("name")
    if name not in (None, LEASE_FILE):
        reasons.append("lease-database.name differs from the managed value")
    ld.require_equal("lfc-interval", 3600)
    ld.leftovers()
    t.require_equal("renew-timer", 900)
    t.require_equal("rebind-timer", 1800)
    default_lifetime = t.take("valid-lifetime", 3600)
    lease_cmds = False
    for hook in t.take("hooks-libraries", []):
        if hook == {"library": HOOK_LEASE_CMDS}:
            lease_cmds = True
        else:
            reasons.append("hook library not supported")
    subs = [_subnet(raw, i, default_lifetime, reasons) for i, raw in enumerate(t.take("subnet4", []))]
    t.leftovers()
    # server_ip comes from the "nic/ip" form of interfaces-config
    by_nic = {}
    for entry in interfaces:
        nic, _, ip = str(entry).partition("/")
        if not ip:
            reasons.append(f"interface {nic[:16]} has no address (nic/ip form required)")
        by_nic[nic] = ip
    for sub in subs:
        sub.server_ip = by_nic.get(sub.interface, "")
        if not sub.server_ip:
            reasons.append(f"subnet {sub.id} interface is not listed in interfaces-config")
    if reasons:
        raise Unsupported(reasons)
    config = DhcpConfig(subs, lease_cmds)
    try:
        validate(config)
    except ValidationError as exc:
        raise Unsupported([f"invalid: {exc.code} {exc.path}"]) from None
    return config
