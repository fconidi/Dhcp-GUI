"""Read-only inventory of Kea, the service, NICs and the configuration state."""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from dataclasses import asdict, dataclass, field

from . import kea_import
from .paths import Paths

OTHER_DHCP_PROCESSES = {"dnsmasq", "dhcpd", "udhcpd", "kea-dhcp4", "dhcpcd-server"}
STATE_FORMAT = 1


@dataclass
class Nic:
    name: str
    up: bool
    addresses: list[str]
    stable: bool          # False when an address comes from a DHCP client


@dataclass
class Inventory:
    kea_installed: bool = False
    kea_version: str = ""
    service_active: str = "unknown"
    service_enabled: str = "unknown"
    nics: list[Nic] = field(default_factory=list)
    other_dhcp: list[str] = field(default_factory=list)
    # kea_missing | pristine | managed | managed_modified | importable | unsupported
    config_state: str = "kea_missing"
    reasons: list[str] = field(default_factory=list)
    writable: bool = False

    def to_dict(self):
        return asdict(self)


def run(cmd, timeout=5):
    try:
        done = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.SubprocessError):
        return 127, ""
    return done.returncode, done.stdout


def sha256_file(path) -> str | None:
    try:
        with open(path, "rb") as fh:
            return hashlib.sha256(fh.read()).hexdigest()
    except OSError:
        return None


def parse_nics(ip_json: str) -> list[Nic]:
    try:
        rows = json.loads(ip_json)
    except ValueError:
        return []
    nics = []
    for row in rows if isinstance(rows, list) else []:
        name = row.get("ifname", "")
        if not name or name == "lo" or "LOOPBACK" in row.get("flags", []):
            continue
        addrs = [f"{a['local']}/{a['prefixlen']}" for a in row.get("addr_info", [])
                 if a.get("family") == "inet" and "local" in a]
        dynamic = any(a.get("dynamic") for a in row.get("addr_info", []) if a.get("family") == "inet")
        nics.append(Nic(name, row.get("operstate", "").upper() in ("UP", "UNKNOWN") or "UP" in row.get("flags", []),
                        addrs, not dynamic))
    return nics


def udp67_listeners(proc_net_udp: str) -> bool:
    for line in proc_net_udp.splitlines()[1:]:
        parts = line.split()
        if len(parts) > 3 and parts[1].rsplit(":", 1)[-1] == "0043":
            return True
    return False


def other_dhcp_servers(paths: Paths) -> list[str]:
    found = set()
    try:
        pids = [p for p in os.listdir(paths.proc) if p.isdigit()]
    except OSError:
        pids = []
    for pid in pids:
        try:
            with open(f"{paths.proc}/{pid}/comm", encoding="utf-8") as fh:
                comm = fh.read().strip()
        except OSError:
            continue
        if comm in OTHER_DHCP_PROCESSES and comm != "kea-dhcp4":
            found.add(comm)
    try:
        with open(f"{paths.proc}/net/udp", encoding="utf-8") as fh:
            if udp67_listeners(fh.read()) and not found:
                found.add("udp/67")
    except OSError:
        pass
    return sorted(found)


def conffile_md5(dpkg_conffiles: str, path: str) -> str | None:
    for line in dpkg_conffiles.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0] == path:
            return parts[1]
    return None


def is_pristine_debian(paths: Paths, runner) -> bool:
    rc, out = runner(["dpkg-query", "-W", "-f=${Conffiles}\\n", "kea-dhcp4-server"])
    expected = conffile_md5(out, "/etc/kea/kea-dhcp4.conf") if rc == 0 else None
    try:
        with open(paths.debian_conf, "rb") as fh:
            actual = hashlib.md5(fh.read(), usedforsecurity=False).hexdigest()
    except OSError:
        return False
    return expected is not None and expected == actual


def read_state(paths: Paths):
    try:
        with open(paths.state, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("format") != STATE_FORMAT or not isinstance(data.get("files"), dict):
        return None
    return data


def collect(paths: Paths = Paths(), runner=run) -> Inventory:
    inv = Inventory()
    rc, out = runner(["dpkg-query", "-W", "-f=${Status}|${Version}", "kea-dhcp4-server"])
    if rc == 0 and out.startswith("install ok installed|"):
        inv.kea_installed, inv.kea_version = True, out.split("|", 1)[1]
    rc, out = runner(["systemctl", "is-active", "kea-dhcp4-server"])
    inv.service_active = out.strip() or ("unknown" if rc == 127 else "inactive")
    rc, out = runner(["systemctl", "is-enabled", "kea-dhcp4-server"])
    inv.service_enabled = out.strip() or ("unknown" if rc == 127 else "disabled")
    rc, out = runner(["ip", "-j", "-4", "addr", "show"])
    inv.nics = parse_nics(out) if rc == 0 else []
    inv.other_dhcp = other_dhcp_servers(paths)
    if not inv.kea_installed:
        return inv
    _classify(inv, paths, runner)
    return inv


def _classify(inv: Inventory, paths: Paths, runner) -> None:
    state = read_state(paths)
    managed_exists = os.path.exists(paths.managed_conf)
    if state is not None or managed_exists:
        files = (state or {}).get("files", {})
        ok = (state is not None and managed_exists
              and files.get(paths.managed_conf) == sha256_file(paths.managed_conf)
              and files.get(paths.dropin) == sha256_file(paths.dropin))
        inv.config_state = "managed" if ok else "managed_modified"
        inv.writable = ok
        if not ok:
            inv.reasons.append("managed files are missing, changed or have no matching state")
        return
    if is_pristine_debian(paths, runner):
        inv.config_state, inv.writable = "pristine", True
        return
    try:
        with open(paths.debian_conf, encoding="utf-8") as fh:
            kea_import.import_config(fh.read())
        inv.config_state = "importable"
    except OSError:
        inv.config_state = "unsupported"
        inv.reasons.append("configuration file cannot be read")
    except kea_import.Unsupported as exc:
        inv.config_state = "unsupported"
        inv.reasons = exc.reasons[:20]
