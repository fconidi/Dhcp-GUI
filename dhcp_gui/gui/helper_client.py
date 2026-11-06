"""Talks to the helper process over stdin/stdout using the versioned protocol."""
from __future__ import annotations

import json
import subprocess
import sys

from ..core import protocol


class HelperError(Exception):
    def __init__(self, code, detail=""):
        super().__init__(f"{code}: {detail}".strip())
        self.code, self.detail = code, detail


class HelperClient:
    def __init__(self, command=None):
        # Read-only operations need no privileges; admin operations will go through pkexec.
        self.command = command or [sys.executable, "-m", "dhcp_gui.helper"]
        self.proc = None

    def start(self):
        if self.proc is None:
            self.proc = subprocess.Popen(self.command, stdin=subprocess.PIPE, stdout=subprocess.PIPE)

    def call(self, op, model=None, **args):
        self.start()
        try:
            self.proc.stdin.write(protocol.encode_request(op, model, **args))
            self.proc.stdin.flush()
            line = self.proc.stdout.readline(protocol.MAX_RESPONSE_BYTES + 2)
        except OSError as exc:
            raise HelperError("unavailable", str(exc)) from None
        if not line:
            raise HelperError("unavailable", "helper closed")
        reply = json.loads(line)
        if not reply.get("ok"):
            err = reply.get("error", {})
            raise HelperError(err.get("code", "internal"), err.get("detail", ""))
        return reply["data"]

    def close(self):
        if self.proc is not None:
            self.proc.stdin.close()
            self.proc.wait(timeout=5)
            self.proc = None
