"""Fixed locations used by the app. A root prefix allows tests to run in a sandbox."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Paths:
    root: str = ""

    def _p(self, path: str) -> str:
        return self.root + path

    @property
    def debian_conf(self): return self._p("/etc/kea/kea-dhcp4.conf")
    @property
    def managed_conf(self): return self._p("/etc/kea/managed/kea-dhcp4.conf")
    @property
    def dropin(self): return self._p("/etc/systemd/system/kea-dhcp4-server.service.d/dhcp-gui.conf")
    @property
    def state(self): return self._p("/var/lib/dhcp-gui/state.json")
    @property
    def backups(self): return self._p("/var/lib/dhcp-gui/backups")
    @property
    def lock(self): return self._p("/run/dhcp-gui.lock")
    @property
    def proc(self): return self._p("/proc")
