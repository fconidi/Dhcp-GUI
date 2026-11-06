"""Typed DHCPv4 model, validation and deterministic Kea JSON generation.

The privileged helper rebuilds the Kea configuration from this model only; nothing
in the output (paths, hook libraries, commands) is taken from the client.
"""
from __future__ import annotations

import ipaddress
import json
import re
from dataclasses import dataclass, field

HOOK_LEASE_CMDS = "/usr/lib/x86_64-linux-gnu/kea/hooks/libdhcp_lease_cmds.so"
CONTROL_SOCKET = "/run/kea/kea4-ctrl-socket"
LEASE_FILE = "/var/lib/kea/kea-leases4.csv"

_IFACE_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,15}$")
_HOST_RE = re.compile(r"^(?=.{1,253}$)([A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?)(\.[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*$")
_MAC_RE = re.compile(r"^[0-9a-f]{2}(:[0-9a-f]{2}){5}$")
_CLIENT_ID_RE = re.compile(r"^[0-9a-f]{2}(:[0-9a-f]{2}){1,31}$")
ID_TYPES = ("hw-address", "client-id")


class ValidationError(ValueError):
    """Carries a stable code, the field path and a human detail."""

    def __init__(self, code: str, path: str, detail: str = ""):
        super().__init__(f"{code}: {path} {detail}".strip())
        self.code, self.path, self.detail = code, path, detail


@dataclass
class Reservation:
    id_type: str
    identifier: str
    ip: str
    hostname: str = ""


@dataclass
class Subnet:
    id: int
    interface: str
    server_ip: str
    subnet: str
    pool_start: str
    pool_end: str
    valid_lifetime: int = 3600
    gateway: str = ""
    dns: list[str] = field(default_factory=list)
    domain: str = ""
    next_server: str = ""
    boot_file: str = ""
    reservations: list[Reservation] = field(default_factory=list)


@dataclass
class DhcpConfig:
    subnets: list[Subnet] = field(default_factory=list)
    lease_cmds: bool = False


def _ip(value, path):
    try:
        return ipaddress.IPv4Address(value)
    except (ipaddress.AddressValueError, ValueError, TypeError):
        raise ValidationError("bad_ip", path, str(value)[:64]) from None


def normalize_identifier(id_type: str, value: str, path: str = "identifier") -> str:
    text = str(value).strip().lower().replace("-", ":")
    if id_type == "hw-address":
        if not _MAC_RE.match(text):
            raise ValidationError("bad_mac", path, text[:64])
    elif id_type == "client-id":
        if not _CLIENT_ID_RE.match(text):
            raise ValidationError("bad_client_id", path, text[:96])
    else:
        raise ValidationError("bad_id_type", path, str(id_type)[:32])
    return text


def _no_control(text: str, path: str, limit: int):
    if len(text) > limit:
        raise ValidationError("too_long", path, f">{limit}")
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in text):
        raise ValidationError("control_chars", path)


def validate_subnet(sub: Subnet, index: int = 0) -> None:
    p = f"subnets[{index}]"
    if not isinstance(sub.id, int) or isinstance(sub.id, bool) or not 1 <= sub.id <= 2**31 - 1:
        raise ValidationError("bad_id", f"{p}.id")
    if not _IFACE_RE.match(sub.interface or ""):
        raise ValidationError("bad_interface", f"{p}.interface", str(sub.interface)[:32])
    try:
        net = ipaddress.IPv4Network(sub.subnet, strict=True)
    except (ValueError, TypeError):
        raise ValidationError("bad_subnet", f"{p}.subnet", str(sub.subnet)[:64]) from None
    if not 8 <= net.prefixlen <= 30:
        raise ValidationError("bad_prefix", f"{p}.subnet", "prefix must be 8-30")
    server = _ip(sub.server_ip, f"{p}.server_ip")
    start, end = _ip(sub.pool_start, f"{p}.pool_start"), _ip(sub.pool_end, f"{p}.pool_end")
    hosts = (net.network_address + 1, net.broadcast_address - 1)

    def inside(addr, path):
        if not hosts[0] <= addr <= hosts[1]:
            raise ValidationError("outside_subnet", path, str(addr))

    inside(server, f"{p}.server_ip")
    inside(start, f"{p}.pool_start")
    inside(end, f"{p}.pool_end")
    if start > end:
        raise ValidationError("pool_order", f"{p}.pool_start")
    if start <= server <= end:
        raise ValidationError("server_in_pool", f"{p}.server_ip")
    if not isinstance(sub.valid_lifetime, int) or isinstance(sub.valid_lifetime, bool) \
            or not 60 <= sub.valid_lifetime <= 604800:
        raise ValidationError("bad_lifetime", f"{p}.valid_lifetime", "60-604800")
    taken = {server}
    if sub.gateway:
        gw = _ip(sub.gateway, f"{p}.gateway")
        inside(gw, f"{p}.gateway")
        if start <= gw <= end:
            raise ValidationError("gateway_in_pool", f"{p}.gateway")
    if len(sub.dns) > 4:
        raise ValidationError("too_many_dns", f"{p}.dns", "max 4")
    for i, entry in enumerate(sub.dns):
        _ip(entry, f"{p}.dns[{i}]")
    if sub.domain and not _HOST_RE.match(sub.domain):
        raise ValidationError("bad_domain", f"{p}.domain", sub.domain[:64])
    if sub.next_server:
        _ip(sub.next_server, f"{p}.next_server")
    _no_control(sub.boot_file, f"{p}.boot_file", 128)
    if len(sub.reservations) > 1024:
        raise ValidationError("too_many_reservations", f"{p}.reservations")
    seen_ids, seen_ips = set(), set()
    if sub.gateway:
        taken.add(ipaddress.IPv4Address(sub.gateway))
    for j, res in enumerate(sub.reservations):
        rp = f"{p}.reservations[{j}]"
        ident = normalize_identifier(res.id_type, res.identifier, f"{rp}.identifier")
        addr = _ip(res.ip, f"{rp}.ip")
        inside(addr, f"{rp}.ip")
        if start <= addr <= end:
            raise ValidationError("reservation_in_pool", f"{rp}.ip", str(addr))
        if addr in taken:
            raise ValidationError("reservation_conflict", f"{rp}.ip", str(addr))
        if res.hostname and not _HOST_RE.match(res.hostname):
            raise ValidationError("bad_hostname", f"{rp}.hostname", res.hostname[:64])
        key = (res.id_type, ident)
        if key in seen_ids:
            raise ValidationError("duplicate_identifier", f"{rp}.identifier", ident)
        if addr in seen_ips:
            raise ValidationError("duplicate_ip", f"{rp}.ip", str(addr))
        seen_ids.add(key)
        seen_ips.add(addr)


def validate(config: DhcpConfig) -> None:
    if len(config.subnets) > 32:
        raise ValidationError("too_many_subnets", "subnets", "max 32")
    ids, ifaces, nets = set(), set(), []
    for i, sub in enumerate(config.subnets):
        validate_subnet(sub, i)
        net = ipaddress.IPv4Network(sub.subnet)
        if sub.id in ids:
            raise ValidationError("duplicate_subnet_id", f"subnets[{i}].id")
        if sub.interface in ifaces:
            raise ValidationError("duplicate_interface", f"subnets[{i}].interface")
        for other in nets:
            if net.overlaps(other):
                raise ValidationError("subnet_overlap", f"subnets[{i}].subnet")
        ids.add(sub.id)
        ifaces.add(sub.interface)
        nets.append(net)


def _subnet_json(sub: Subnet) -> dict:
    options = []
    if sub.gateway:
        options.append({"name": "routers", "data": sub.gateway})
    if sub.dns:
        options.append({"name": "domain-name-servers", "data": ", ".join(sub.dns)})
    if sub.domain:
        options.append({"name": "domain-name", "data": sub.domain})
    out = {
        "id": sub.id,
        "subnet": str(ipaddress.IPv4Network(sub.subnet)),
        "interface": sub.interface,
        "valid-lifetime": sub.valid_lifetime,
        "pools": [{"pool": f"{sub.pool_start} - {sub.pool_end}"}],
    }
    if options:
        out["option-data"] = options
    if sub.next_server:
        out["next-server"] = sub.next_server
    if sub.boot_file:
        out["boot-file-name"] = sub.boot_file
    if sub.reservations:
        out["reservations"] = [
            {res.id_type: normalize_identifier(res.id_type, res.identifier), "ip-address": res.ip,
             **({"hostname": res.hostname} if res.hostname else {})}
            for res in sorted(sub.reservations, key=lambda r: ipaddress.IPv4Address(r.ip))
        ]
    return out


def to_kea(config: DhcpConfig) -> dict:
    validate(config)
    subnets = sorted(config.subnets, key=lambda s: s.id)
    dhcp = {
        "interfaces-config": {
            "interfaces": [f"{s.interface}/{s.server_ip}" for s in subnets],
            "service-sockets-require-all": False,
            "service-sockets-max-retries": 10,
            "service-sockets-retry-wait-time": 5000,
        },
        "control-socket": {"socket-type": "unix", "socket-name": CONTROL_SOCKET},
        "lease-database": {"type": "memfile", "name": LEASE_FILE, "lfc-interval": 3600},
        "renew-timer": 900,
        "rebind-timer": 1800,
        "subnet4": [_subnet_json(s) for s in subnets],
    }
    if config.lease_cmds:
        dhcp["hooks-libraries"] = [{"library": HOOK_LEASE_CMDS}]
    return {"Dhcp4": dhcp}


def render(config: DhcpConfig) -> str:
    return json.dumps(to_kea(config), indent=2, sort_keys=True) + "\n"
