"""Helper request loop: one JSON line in, one JSON line out.

Task 3 serves the read-only operations. Mutating operations answer 'unavailable'
until the safe apply machinery exists.
"""
from __future__ import annotations

import sys

from ..core import inventory, model, protocol
from ..core.paths import Paths
from ..core.protocol import OPERATIONS, ProtocolError


def handle(line: bytes, paths: Paths = Paths(), runner=inventory.run) -> bytes:
    try:
        op, _args, cfg = protocol.parse_request(line)
    except ProtocolError as exc:
        return protocol.error(exc.code, exc.detail)
    try:
        if op == "ping":
            return protocol.ok(pong=True)
        if op == "inventory":
            return protocol.ok(**inventory.collect(paths, runner).to_dict())
        if op == "preview":
            return protocol.ok(json=model.render(cfg))
    except model.ValidationError as exc:
        return protocol.validation_error(exc)
    except Exception:  # never leak internals to the client
        return protocol.error("internal")
    return protocol.error("unavailable", f"{op} is not implemented yet")


def serve(stdin=None, stdout=None) -> int:
    stdin = stdin or sys.stdin.buffer
    stdout = stdout or sys.stdout.buffer
    while True:
        line = stdin.readline(protocol.MAX_REQUEST_BYTES + 2)
        if not line:
            return 0
        stdout.write(handle(line.rstrip(b"\n")))
        stdout.flush()
