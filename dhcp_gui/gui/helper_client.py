"""Talks to the helper processes using the versioned protocol.

`none` operations use one long-lived unprivileged process. `read` and `write`
operations start a one-shot privileged process through pkexec, so polkit decides
on every request and the privileged helper never outlives it.
"""
from __future__ import annotations

import json
import subprocess
import sys

from ..core import protocol

PKEXEC = {"read": ["pkexec", "/usr/lib/dhcp-gui/dhcp-gui-helper-read"],
          "write": ["pkexec", "/usr/lib/dhcp-gui/dhcp-gui-helper-write"]}


class HelperError(Exception):
    def __init__(self, code, detail=""):
        super().__init__(f"{code}: {detail}".strip())
        self.code, self.detail = code, detail


class HelperClient:
    def __init__(self, commands=None):
        self.commands = {"none": [sys.executable, "-m", "dhcp_gui.helper"], **PKEXEC, **(commands or {})}
        self.proc = None

    def _exchange(self, command, payload, keep):
        try:
            if keep:
                if self.proc is None:
                    self.proc = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE)
                self.proc.stdin.write(payload)
                self.proc.stdin.flush()
                return self.proc.stdout.readline(protocol.MAX_RESPONSE_BYTES + 2)
            done = subprocess.run(command, input=payload, capture_output=True, timeout=180, check=False)
        except (OSError, subprocess.SubprocessError) as exc:
            raise HelperError("unavailable", str(exc)[:100]) from None
        if done.returncode in (126, 127):
            raise HelperError("denied", "authorization was not granted")
        return done.stdout

    def call(self, op, model=None, **args):
        klass = protocol.OPERATIONS[op]
        line = self._exchange(self.commands[klass], protocol.encode_request(op, model, **args), klass == "none")
        if not line:
            raise HelperError("unavailable", "no answer from the helper")
        try:
            reply = json.loads(line)
        except ValueError:
            raise HelperError("internal", "invalid answer") from None
        if not reply.get("ok"):
            err = reply.get("error", {})
            detail = err.get("detail", "")
            if err.get("path"):
                detail = f"{detail}|{err['path']}"
            raise HelperError(err.get("code", "internal"), detail)
        return reply["data"]

    def close(self):
        if self.proc is not None:
            self.proc.stdin.close()
            self.proc.wait(timeout=5)
            self.proc = None
