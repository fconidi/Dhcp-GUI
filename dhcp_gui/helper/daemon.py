"""Helper request loop: one JSON line in, one JSON line out.

Task 3 serves the read-only operations. Mutating operations answer 'unavailable'
until the safe apply machinery exists.
"""
from __future__ import annotations

import os
import sys

from ..core import apply as applymod
from ..core import inventory, kea_import, model, protocol, service
from ..core.paths import Paths
from ..core.protocol import OPERATIONS, ProtocolError


def handle(line: bytes, paths: Paths = Paths(), runner=inventory.run, ops=None, allowed=None) -> bytes:
    """`allowed` lists the authorization classes this process may serve."""
    try:
        op, _args, cfg = protocol.parse_request(line)
    except ProtocolError as exc:
        return protocol.error(exc.code, exc.detail)
    if allowed is not None and OPERATIONS[op] not in allowed:
        return protocol.error("denied", f"{op} is not served by this helper")
    ops = ops or applymod.SystemOps()
    try:
        if op == "ping":
            return protocol.ok(pong=True)
        if op == "inventory":
            return protocol.ok(**inventory.collect(paths, runner).to_dict())
        if op == "current":
            inv = inventory.collect(paths, runner)
            source = {"managed": paths.managed_conf, "managed_modified": None, "importable": paths.debian_conf}.get(inv.config_state)
            if not source:
                return protocol.ok(state=inv.config_state, model=None)
            with open(source, encoding="utf-8") as fh:
                imported = kea_import.import_config(fh.read())
            return protocol.ok(state=inv.config_state, model=protocol.model_to_dict(imported))
        if op == "preview":
            return protocol.ok(json=model.render(cfg))
        if op == "verify":
            model.validate(cfg)
            return protocol.ok(valid=True)
        if op == "apply":
            res = applymod.Applier(paths, ops, runner).apply(cfg, _args["token"])
            return protocol.ok(action=res.action, backup=res.backup, steps=res.steps)
        if op == "restore":
            res = applymod.Applier(paths, ops, runner).restore_last()
            return protocol.ok(action=res.action, backup=res.backup)
        if op == "service_start":
            return protocol.ok(**service.start(paths, ops, runner))
        if op == "service_stop":
            return protocol.ok(**service.stop(paths, ops, runner))
        if op == "stats":
            return protocol.ok(**service.stats())
        if op == "leases":
            return protocol.ok(**service.leases(_args.get("from_ip", "start"), _args.get("limit", 100)))
    except model.ValidationError as exc:
        return protocol.validation_error(exc)
    except kea_import.Unsupported:
        return protocol.ok(state="unsupported", model=None)
    except OSError:
        return protocol.error("unavailable", "cannot read configuration")
    except applymod.ApplyError as exc:
        return protocol.error(exc.code if exc.code in protocol.ERROR_CODES else "internal",
                              f"{exc.detail} [outcome={exc.outcome} service={exc.service}]")
    except Exception:  # never leak internals to the client
        return protocol.error("internal")
    return protocol.error("unavailable", f"{op} is not implemented")


def serve(stdin=None, stdout=None, allowed=None, once=False) -> int:
    stdin = stdin or sys.stdin.buffer
    stdout = stdout or sys.stdout.buffer
    while True:
        line = stdin.readline(protocol.MAX_REQUEST_BYTES + 2)
        if not line:
            return 0
        stdout.write(handle(line.rstrip(b"\n"), allowed=allowed))
        stdout.flush()
        if once:
            return 0


CLASSES = {"none": {"none"}, "read": {"none", "read"}, "write": {"none", "read", "write"}}


def main(mode: str) -> int:
    """Entry point for the helper processes.

    The classes served are fixed by the installed wrapper that calls this function
    (never by the client). Privileged modes answer one request and exit.
    """
    if mode not in CLASSES:
        return 2
    if mode != "none":
        os.environ["PATH"] = "/usr/sbin:/usr/bin:/sbin:/bin"
        os.umask(0o022)
    return serve(allowed=CLASSES[mode], once=mode != "none")
