"""Suggestions for the wizard: derived from the NIC address, never from fixed ranges."""
from __future__ import annotations

import ipaddress
from dataclasses import dataclass


@dataclass
class Suggestion:
    subnet: str
    server_ip: str
    pool_start: str
    pool_end: str


def suggest(nic_address: str, gateway: str = "") -> Suggestion:
    """nic_address is 'ip/prefix'. The pool avoids the server and the gateway."""
    iface = ipaddress.IPv4Interface(nic_address)
    net = iface.network
    if not 8 <= net.prefixlen <= 30:
        raise ValueError("prefix must be 8-30")
    first, last = int(net.network_address) + 1, int(net.broadcast_address) - 1
    total = last - first + 1
    reserve = max(0, total // 10)               # low addresses kept for static devices
    lo = first + reserve
    blocked = sorted({int(iface.ip)} | ({int(ipaddress.IPv4Address(gateway))} if gateway else set()))
    segments, cur = [], lo
    for b in blocked + [last + 1]:
        if b >= cur:
            if b - 1 >= cur:
                segments.append((cur, min(b - 1, last)))
            cur = max(cur, b + 1)
    if not segments:  # tiny network: fall back to the whole host range minus blocked
        segments = [(first, last)] if first != int(iface.ip) else []
    if not segments:
        raise ValueError("no address left for a pool")
    start, end = max(segments, key=lambda seg: seg[1] - seg[0])
    return Suggestion(str(net), str(iface.ip), str(ipaddress.IPv4Address(start)), str(ipaddress.IPv4Address(end)))
