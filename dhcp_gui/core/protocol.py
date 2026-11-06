"""Versioned request/response contract between the GUI and the root helper.

One JSON object per line. The client sends an operation name and, for operations
that change state, a typed model; it never sends Kea JSON, paths, units or commands.
"""
from __future__ import annotations

import json
from dataclasses import asdict

from .model import DhcpConfig, Reservation, Subnet, ValidationError

PROTOCOL_VERSION = 1
MAX_REQUEST_BYTES = 256 * 1024
MAX_RESPONSE_BYTES = 1024 * 1024

# operation -> authorization class (maps to a distinct polkit action)
OPERATIONS = {
    "ping": "none",
    "inventory": "none",        # minimal public state only
    "preview": "none",          # renders JSON from a model, writes nothing
    "verify": "admin",
    "apply": "admin",
    "restore": "admin",
    "service_start": "admin",
    "service_stop": "admin",
    "stats": "none",
    "leases": "admin",          # lease data is sensitive
}
MODEL_OPERATIONS = {"preview", "verify", "apply"}
ERROR_CODES = {
    "bad_request", "bad_version", "unknown_operation", "too_large", "validation",
    "denied", "conflict", "not_managed", "kea_missing", "kea_rejected", "apply_failed",
    "restore_failed", "unavailable", "internal",
}

_SUBNET_KEYS = {f for f in Subnet.__dataclass_fields__}
_RES_KEYS = {f for f in Reservation.__dataclass_fields__}
_CFG_KEYS = {f for f in DhcpConfig.__dataclass_fields__}


class ProtocolError(Exception):
    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}".strip())
        self.code, self.detail = code, detail


def _only(obj, keys, what):
    if not isinstance(obj, dict):
        raise ProtocolError("bad_request", f"{what} must be an object")
    extra = set(obj) - keys
    if extra:
        raise ProtocolError("bad_request", f"unknown field in {what}: {sorted(extra)[0][:32]}")
    return obj


def _typed(obj, name, kind, default):
    value = obj.get(name, default)
    if not isinstance(value, kind) or (kind is int and isinstance(value, bool)):
        raise ProtocolError("bad_request", f"{name} has the wrong type")
    return value


def model_from_dict(data) -> DhcpConfig:
    data = _only(data, _CFG_KEYS, "model")
    subnets = []
    raw_subnets = _typed(data, "subnets", list, [])
    for raw in raw_subnets:
        raw = _only(raw, _SUBNET_KEYS, "subnet")
        res_list = []
        for rr in _typed(raw, "reservations", list, []):
            rr = _only(rr, _RES_KEYS, "reservation")
            res_list.append(Reservation(
                id_type=_typed(rr, "id_type", str, ""), identifier=_typed(rr, "identifier", str, ""),
                ip=_typed(rr, "ip", str, ""), hostname=_typed(rr, "hostname", str, "")))
        dns = _typed(raw, "dns", list, [])
        if not all(isinstance(item, str) for item in dns):
            raise ProtocolError("bad_request", "dns has the wrong type")
        subnets.append(Subnet(
            id=_typed(raw, "id", int, 0), interface=_typed(raw, "interface", str, ""),
            server_ip=_typed(raw, "server_ip", str, ""), subnet=_typed(raw, "subnet", str, ""),
            pool_start=_typed(raw, "pool_start", str, ""), pool_end=_typed(raw, "pool_end", str, ""),
            valid_lifetime=_typed(raw, "valid_lifetime", int, 3600), gateway=_typed(raw, "gateway", str, ""),
            dns=list(dns), domain=_typed(raw, "domain", str, ""), next_server=_typed(raw, "next_server", str, ""),
            boot_file=_typed(raw, "boot_file", str, ""), reservations=res_list))
    return DhcpConfig(subnets=subnets, lease_cmds=_typed(data, "lease_cmds", bool, False))


def model_to_dict(config: DhcpConfig) -> dict:
    return asdict(config)


def encode_request(op: str, model: DhcpConfig | None = None, **args) -> bytes:
    body = {"version": PROTOCOL_VERSION, "op": op, "args": args}
    if model is not None:
        body["model"] = model_to_dict(model)
    return (json.dumps(body, separators=(",", ":")) + "\n").encode()


def parse_request(line: bytes):
    """Return (op, args, model_or_None) or raise ProtocolError."""
    if len(line) > MAX_REQUEST_BYTES:
        raise ProtocolError("too_large")
    try:
        body = json.loads(line.decode("utf-8"))
    except (UnicodeDecodeError, ValueError):
        raise ProtocolError("bad_request", "not JSON") from None
    body = _only(body, {"version", "op", "args", "model"}, "request")
    if body.get("version") != PROTOCOL_VERSION:
        raise ProtocolError("bad_version")
    op = body.get("op")
    if not isinstance(op, str) or op not in OPERATIONS:
        raise ProtocolError("unknown_operation", str(op)[:32])
    args = body.get("args", {})
    if not isinstance(args, dict):
        raise ProtocolError("bad_request", "args must be an object")
    if op in ("leases",):
        args = _only(args, {"from_ip", "limit"}, "args")
        limit = args.get("limit", 100)
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 1000:
            raise ProtocolError("bad_request", "limit must be 1-1000")
    else:
        _only(args, set(), "args")
    model = None
    if op in MODEL_OPERATIONS:
        if "model" not in body:
            raise ProtocolError("bad_request", "model is required")
        model = model_from_dict(body["model"])
    elif "model" in body:
        raise ProtocolError("bad_request", "model is not accepted here")
    return op, args, model


def ok(**data) -> bytes:
    return _encode({"version": PROTOCOL_VERSION, "ok": True, "data": data})


def error(code: str, detail: str = "", path: str = "") -> bytes:
    if code not in ERROR_CODES:
        code = "internal"
    return _encode({"version": PROTOCOL_VERSION, "ok": False,
                    "error": {"code": code, "detail": detail[:200], "path": path[:100]}})


def validation_error(exc: ValidationError) -> bytes:
    return error("validation", exc.code + (f": {exc.detail}" if exc.detail else ""), exc.path)


def _encode(body: dict) -> bytes:
    raw = (json.dumps(body, separators=(",", ":")) + "\n").encode()
    if len(raw) > MAX_RESPONSE_BYTES:
        return error("too_large")
    return raw
