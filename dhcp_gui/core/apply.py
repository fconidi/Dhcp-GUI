"""Safe, persistent application of a configuration.

State machine: INVENTORY -> VALIDATE -> BACKUP -> WRITE_ATOMIC -> RELOAD_OR_START -> VERIFY -> COMMIT,
and after an error RESTORE -> REAPPLY -> VERIFY. All system effects go through `SystemOps`
so every step can be failure-injected in tests.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import shutil
import time
from dataclasses import dataclass, field

from . import inventory, model
from .paths import Paths

DROPIN_TEXT = ("[Service]\n"
               "ExecStart=\n"
               "ExecStart=/usr/sbin/kea-dhcp4 -c /etc/kea/managed/kea-dhcp4.conf\n")
UNIT = "kea-dhcp4-server"
KEEP_BACKUPS = 10


class ApplyError(Exception):
    def __init__(self, code, detail="", outcome="unchanged", service="unknown"):
        super().__init__(f"{code}: {detail}")
        self.code, self.detail, self.outcome, self.service = code, detail, outcome, service


class SystemOps:
    """Real effects. Tests replace individual methods."""

    def run(self, cmd, timeout=30):
        return inventory.run(cmd, timeout)

    def kea_test(self, path):
        """Return (ok, message). Runs with the service user when it exists."""
        rc, out = self.run(["runuser", "-u", "_kea", "--", "/usr/sbin/kea-dhcp4", "-t", path], 30)
        return rc == 0, out[-300:]

    def write_atomic(self, path, data: bytes, mode):
        directory = os.path.dirname(path)
        os.makedirs(directory, exist_ok=True)
        tmp = f"{path}.tmp-{os.getpid()}"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
        try:
            with os.fdopen(fd, "wb") as fh:
                fh.write(data)
                fh.flush()
                os.fsync(fh.fileno())
            os.chmod(tmp, mode)
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    def systemctl(self, *args):
        rc, _out = self.run(["systemctl", *args], 60)
        return rc == 0

    def is_active(self):
        rc, out = self.run(["systemctl", "is-active", UNIT])
        return out.strip() == "active"

    def ctl(self, command, arguments=None):
        """Send one command on the Kea control socket; return the parsed answer or None."""
        from . import kea_ctl
        return kea_ctl.send(command, arguments)


@dataclass
class Result:
    ok: bool
    action: str = "none"          # none | reload | restart
    backup: str = ""
    outcome: str = "applied"      # applied | unchanged | restored | restore_failed
    service: str = "unknown"      # active_new | active_old | active_uncertain | down | unknown
    steps: list = field(default_factory=list)


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class Applier:
    def __init__(self, paths: Paths = Paths(), ops: SystemOps | None = None, runner=inventory.run):
        self.paths, self.ops, self.runner = paths, ops or SystemOps(), runner
        self.steps: list[str] = []

    # -- helpers ---------------------------------------------------------
    def _files(self):
        p = self.paths
        return [p.managed_conf, p.dropin, p.state]

    def _step(self, name):
        self.steps.append(name)

    def _backup(self) -> str:
        bid = time.strftime("%Y%m%d-%H%M%S") + f"-{os.getpid()}"
        base = f"{self.paths.backups}/{bid}"
        os.makedirs(base, mode=0o700, exist_ok=True)
        os.chmod(self.paths.backups, 0o700)
        manifest = {}
        for i, path in enumerate(self._files()):
            if os.path.exists(path):
                shutil.copyfile(path, f"{base}/{i}")
                os.chmod(f"{base}/{i}", 0o600)
                manifest[path] = f"{base}/{i}"
            else:
                manifest[path] = None
        with open(f"{base}/manifest.json", "w", encoding="utf-8") as fh:
            json.dump(manifest, fh)
        os.chmod(f"{base}/manifest.json", 0o600)
        marker = f"{self.paths.backups}/IN_PROGRESS"
        with open(marker, "w", encoding="utf-8") as fh:
            fh.write(bid)
        os.chmod(marker, 0o600)
        self._prune()
        return bid

    def _prune(self):
        try:
            entries = sorted(e for e in os.listdir(self.paths.backups) if e != "IN_PROGRESS")
        except OSError:
            return
        for old in entries[:-KEEP_BACKUPS]:
            shutil.rmtree(f"{self.paths.backups}/{old}", ignore_errors=True)

    def _marker(self):
        return f"{self.paths.backups}/IN_PROGRESS"

    def _last_backup(self):
        try:
            if os.path.exists(self._marker()):
                with open(self._marker(), encoding="utf-8") as fh:
                    return fh.read().strip()
            entries = sorted(e for e in os.listdir(self.paths.backups) if e != "IN_PROGRESS")
        except OSError:
            return None
        return entries[-1] if entries else None

    def _restore_files(self, bid):
        with open(f"{self.paths.backups}/{bid}/manifest.json", encoding="utf-8") as fh:
            manifest = json.load(fh)
        if set(manifest) != set(self._files()):
            raise ApplyError("restore_failed", "backup manifest does not match", "restore_failed")
        for path, saved in manifest.items():
            if saved is None:
                if os.path.exists(path):
                    os.unlink(path)
            else:
                with open(saved, "rb") as fh:
                    self.ops.write_atomic(path, fh.read(), 0o600 if path == self.paths.state else 0o644)

    def _activate(self, action):
        """Make the running service use the files on disk. Returns the action taken."""
        if action == "none":
            return "none"
        if not self.ops.systemctl("daemon-reload"):
            raise ApplyError("apply_failed", "daemon-reload failed")
        if action == "reload":
            answer = self.ops.ctl("config-reload")
            if answer and answer[0].get("result") == 0:
                return "reload"
            action = "restart"
        if not self.ops.systemctl("restart", UNIT):
            raise ApplyError("apply_failed", "restart failed")
        return "restart"

    def _verify(self, action):
        if action == "none":
            return
        if not self.ops.is_active():
            raise ApplyError("apply_failed", "service is not active after the change")
        answer = self.ops.ctl("status-get")
        if not answer or answer[0].get("result") != 0:
            raise ApplyError("apply_failed", "Kea does not answer on its control socket")

    # -- public ----------------------------------------------------------
    def apply(self, config: model.DhcpConfig, token: str) -> Result:
        os.makedirs(os.path.dirname(self.paths.lock) or "/", exist_ok=True)
        with open(self.paths.lock, "a+") as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                raise ApplyError("conflict", "another change is in progress") from None
            return self._apply_locked(config, token)

    def _apply_locked(self, config, token) -> Result:
        self._step("INVENTORY")
        inv = inventory.collect(self.paths, self.runner)
        if not inv.kea_installed:
            raise ApplyError("kea_missing")
        if inv.token != token:
            raise ApplyError("conflict", "configuration changed since it was read")
        if inv.config_state not in ("pristine", "managed", "importable"):  # importable = explicit adoption
            raise ApplyError("not_managed", inv.config_state)
        self._step("VALIDATE")
        try:
            text = model.render(config).encode()
        except model.ValidationError as exc:
            raise ApplyError("validation", f"{exc.code} {exc.path}") from None
        was_active = self.ops.is_active()
        first_time = inv.config_state != "managed" or not os.path.exists(self.paths.dropin)
        planned = "none" if not was_active else ("restart" if first_time else "reload")
        self._step("TEST")
        probe = f"{os.path.dirname(self.paths.managed_conf)}/.check-kea-dhcp4.conf"
        os.makedirs(os.path.dirname(probe), exist_ok=True)
        self.ops.write_atomic(probe, text, 0o644)
        try:
            ok, msg = self.ops.kea_test(probe)
        finally:
            if os.path.exists(probe):
                os.unlink(probe)
        if not ok:
            raise ApplyError("kea_rejected", msg)
        self._step("BACKUP")
        bid = self._backup()
        try:
            self._step("WRITE_ATOMIC")
            self.ops.write_atomic(self.paths.managed_conf, text, 0o644)
            self.ops.write_atomic(self.paths.dropin, DROPIN_TEXT.encode(), 0o644)
            state = {"format": inventory.STATE_FORMAT, "files": {
                self.paths.managed_conf: _sha(text), self.paths.dropin: _sha(DROPIN_TEXT.encode())}}
            self.ops.write_atomic(self.paths.state, json.dumps(state).encode(), 0o600)
            self._step("RELOAD_OR_START")
            action = self._activate(planned)
            self._step("VERIFY")
            self._verify(action)
        except (ApplyError, OSError) as exc:
            return self._recover(bid, planned, exc)
        self._step("COMMIT")
        os.unlink(self._marker())
        return Result(True, action, bid, "applied", "active_new" if action != "none" else "unknown", self.steps)

    def _recover(self, bid, planned, exc) -> Result:
        self._step("RESTORE")
        try:
            self._restore_files(bid)
        except (ApplyError, OSError, ValueError) as err:
            raise ApplyError("restore_failed", f"{exc}; restore: {err}", "restore_failed") from None
        os.unlink(self._marker())
        self._step("REAPPLY")
        service = "unknown"
        try:
            action = self._activate(planned)
            self._verify(action)
            service = "active_old" if action != "none" else "unknown"
        except ApplyError:
            service = "active_uncertain" if self.ops.is_active() else "down"
        detail = str(exc)
        raise ApplyError("apply_failed", detail, "restored" if service in ("active_old", "unknown") else "restore_failed",
                         service)

    def restore_last(self) -> Result:
        bid = self._last_backup()
        if not bid:
            raise ApplyError("unavailable", "no backup")
        with open(self.paths.lock, "a+") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            self._restore_files(bid)
            if os.path.exists(self._marker()):
                os.unlink(self._marker())
            action = self._activate("restart" if self.ops.is_active() else "none")
            self._verify(action)
        return Result(True, action, bid, "restored", "active_old", self.steps)
