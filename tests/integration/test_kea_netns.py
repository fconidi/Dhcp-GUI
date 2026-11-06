"""Real Kea in a network namespace, with a real DHCP client over a veth pair.

Runs only when DHCP_GUI_INTEGRATION=1, as root, with DHCP_GUI_CHROOT pointing at a
Debian root that has kea-dhcp4-server installed. It never touches the real network:
both ends of the veth pair live in private namespaces.
"""
import hashlib
import os
import re
import signal
import subprocess
import tempfile
import time
import unittest

from dhcp_gui.core import apply as ap
from dhcp_gui.core import inventory, kea_ctl, model, service
from dhcp_gui.core.model import DhcpConfig, Reservation, Subnet
from dhcp_gui.core.paths import Paths

CHROOT = os.environ.get("DHCP_GUI_CHROOT", "")
ENABLED = os.environ.get("DHCP_GUI_INTEGRATION") == "1" and os.geteuid() == 0 and os.path.isdir(CHROOT)
SRV, CLI = "dgsrv", "dgcli"
RESERVED_MAC = "02:00:00:aa:bb:01"


def sh(*cmd, check=True, **kw):
    return subprocess.run(cmd, check=check, capture_output=True, text=True, **kw)


def cfg(pool_end="192.168.50.200", lease_cmds=True, iface="dgs0"):
    return DhcpConfig([Subnet(
        1, iface, "192.168.50.1", "192.168.50.0/24", "192.168.50.100", pool_end, valid_lifetime=600,
        gateway="192.168.50.254", dns=["192.168.50.53"],
        reservations=[Reservation("hw-address", RESERVED_MAC, "192.168.50.10", "reserved")])], lease_cmds)


class RealOps(ap.SystemOps):
    """Real Kea and real control socket; systemd is replaced by a process in the namespace."""

    def __init__(self, root):
        self.root, self.proc, self.fail_status_once = root, None, False
        self.sock = root + kea_ctl.SOCKET_PATH

    def run(self, cmd, timeout=30):
        return 127, ""

    def _inside(self, path):
        return path[len(self.root):] if path.startswith(self.root) else path

    def kea_test(self, path):
        done = sh("ip", "netns", "exec", SRV, "chroot", self.root, "runuser", "-u", "_kea", "--",
                  "/usr/sbin/kea-dhcp4", "-t", self._inside(path), check=False)
        return done.returncode == 0, (done.stdout + done.stderr)[-300:]

    def _start(self):
        if self.is_active():
            return
        if os.path.exists(self.sock):
            os.unlink(self.sock)
        self.proc = subprocess.Popen(
            ["ip", "netns", "exec", SRV, "chroot", self.root, "setpriv", "--reuid=_kea", "--regid=_kea",
             "--init-groups", "--inh-caps=+net_bind_service,+net_raw",
             "--ambient-caps=+net_bind_service,+net_raw",       # what the systemd unit grants
             "/usr/sbin/kea-dhcp4", "-c", "/etc/kea/managed/kea-dhcp4.conf"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        for _ in range(50):
            if kea_ctl.send("status-get", path=self.sock):
                return
            time.sleep(0.1)

    def stop_process(self):
        if self.proc is not None:
            sh("pkill", "-f", "kea-dhcp4 -c /etc/kea/managed", check=False)
            self.proc.wait(timeout=10)
            self.proc = None

    def systemctl(self, *args):
        if args[0] in ("daemon-reload",):
            return True
        if args[:2] == ("enable", "--now") or args[0] == "restart":
            self.stop_process()
            self._start()
            return self.is_active()
        if args[:2] == ("disable", "--now"):
            self.stop_process()
            return True
        return False

    def is_active(self):
        return self.proc is not None and self.proc.poll() is None

    def ctl(self, command, arguments=None):
        if command == "status-get" and self.fail_status_once:
            self.fail_status_once = False
            return None
        return kea_ctl.send(command, arguments, path=self.sock)


@unittest.skipUnless(ENABLED, "integration test disabled")
class KeaNetnsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.work = tempfile.mkdtemp(prefix="dg-it-", dir=os.environ.get("DHCP_GUI_TEST_DIR") or None)
        for ns in (SRV, CLI):
            sh("ip", "netns", "del", ns, check=False)
            sh("ip", "netns", "add", ns)
        sh("ip", "link", "add", "dgs0", "type", "veth", "peer", "name", "dgc0")
        sh("ip", "link", "set", "dgs0", "netns", SRV)
        sh("ip", "link", "set", "dgc0", "netns", CLI)
        sh("ip", "netns", "exec", SRV, "ip", "addr", "add", "192.168.50.1/24", "dev", "dgs0")
        sh("ip", "netns", "exec", SRV, "ip", "link", "set", "dgs0", "up")
        sh("ip", "netns", "exec", CLI, "ip", "link", "set", "dgc0", "up")
        cls.paths = Paths(CHROOT)
        cls.ops = RealOps(CHROOT)
        for d in ("/run/kea", "/var/lib/kea", "/var/log/kea"):
            sh("chroot", CHROOT, "sh", "-c", f"mkdir -p {d} && chown _kea {d} && chmod 750 {d}")
        if os.path.exists(cls.paths.managed_conf):
            raise unittest.SkipTest("chroot already has managed files; use a clean chroot copy")
        text = open(cls.paths.debian_conf, "rb").read()
        cls.md5 = hashlib.md5(text).hexdigest()

    @classmethod
    def tearDownClass(cls):
        cls.ops.stop_process()
        for ns in (SRV, CLI):
            sh("ip", "netns", "del", ns, check=False)
        for p in (cls.paths.managed_conf, cls.paths.dropin, cls.paths.state):
            if os.path.exists(p):
                os.unlink(p)
        sh("rm", "-rf", cls.paths.backups, CHROOT + "/var/lib/kea/kea-leases4.csv", check=False)

    # -- helpers -----------------------------------------------------------
    @classmethod
    def runner(cls, cmd, timeout=5):
        if "${Conffiles}\\n" in " ".join(cmd):
            return 0, f" /etc/kea/kea-dhcp4.conf {cls.md5}\n"
        if cmd[0] == "dpkg-query":
            return 0, "install ok installed|test"
        return 127, ""

    def applier(self):
        return ap.Applier(self.paths, self.ops, self.runner)

    def token(self):
        return inventory.collect(self.paths, self.runner).token

    def dhcp(self, mac):
        sh("ip", "netns", "exec", CLI, "ip", "link", "set", "dgc0", "down")
        sh("ip", "netns", "exec", CLI, "ip", "link", "set", "dgc0", "address", mac)
        sh("ip", "netns", "exec", CLI, "ip", "link", "set", "dgc0", "up")
        lease = os.path.join(self.work, "lease-" + mac.replace(":", ""))
        proc = subprocess.Popen(["ip", "netns", "exec", CLI, "dhclient", "-d", "-1", "-sf", "/bin/true",
                                 "-lf", lease, "-pf", lease + ".pid", "dgc0"],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        try:
            for _ in range(150):
                if os.path.exists(lease):
                    m = re.search(r"fixed-address ([0-9.]+);", open(lease).read())
                    if m:
                        return m.group(1)
                time.sleep(0.1)
        finally:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            proc.wait(timeout=10)
        return None

    # -- the scenario, in order ----------------------------------------------
    def test_01_to_09_full_lifecycle(self):
        # 1. adopt the pristine Debian install: real `kea-dhcp4 -t`, service stopped, nothing started
        res = self.applier().apply(cfg(), self.token())
        self.assertEqual((res.ok, res.action), (True, "none"))
        self.assertEqual(inventory.collect(self.paths, self.runner).config_state, "managed")
        self.assertIn("Dhcp4", open(self.paths.debian_conf).read())            # Debian conffile untouched
        # 2. start the service through the app logic
        self.assertTrue(service.start(self.paths, self.ops, self.runner)["active"])
        # 3. real DHCP exchange: dynamic address from the pool
        ip = self.dhcp("02:00:00:00:00:77")
        self.assertIsNotNone(ip, "no DHCP lease obtained")
        self.assertTrue(100 <= int(ip.split(".")[-1]) <= 200, ip)
        # 4. reservation honoured
        self.assertEqual(self.dhcp(RESERVED_MAC), "192.168.50.10")
        # 5. renewal / re-request keeps the address
        self.assertEqual(self.dhcp(RESERVED_MAC), "192.168.50.10")
        # 6. statistics and lease list from the real control socket
        stats = service.stats(lambda c, a=None: kea_ctl.send(c, a, path=self.ops.sock))
        sub = stats["subnets"][0]
        self.assertEqual(sub["total"], 101)
        self.assertGreaterEqual(sub["assigned"], 1)
        page = service.leases("start", 50, lambda c, a=None: kea_ctl.send(c, a, path=self.ops.sock))
        self.assertIn("192.168.50.10", [row["ip"] for row in page["leases"]])
        # 7. change while running: config-reload, not restart
        res = self.applier().apply(cfg("192.168.50.210"), self.token())
        self.assertEqual(res.action, "reload")
        stats = service.stats(lambda c, a=None: kea_ctl.send(c, a, path=self.ops.sock))
        self.assertEqual(stats["subnets"][0]["total"], 111)
        # 8. Kea rejects a model that is valid in Python but wrong on this machine: nothing changes
        before = open(self.paths.managed_conf, "rb").read()
        with self.assertRaises(ap.ApplyError) as cm:
            self.applier().apply(cfg(iface="nope0"), self.token())
        self.assertEqual(cm.exception.code, "kea_rejected")
        self.assertEqual(open(self.paths.managed_conf, "rb").read(), before)
        # 9. a failure after the write restores the previous configuration and the service keeps serving
        self.ops.fail_status_once = True
        with self.assertRaises(ap.ApplyError) as cm:
            self.applier().apply(cfg("192.168.50.220"), self.token())
        self.assertEqual((cm.exception.outcome, cm.exception.service), ("restored", "active_old"))
        self.assertEqual(open(self.paths.managed_conf, "rb").read(), before)
        self.assertTrue(self.ops.is_active())
        self.assertEqual(self.dhcp(RESERVED_MAC), "192.168.50.10")
        # 10. restart (what a reboot does): same files, leases persist, clients served as before
        self.ops.systemctl("restart", "kea-dhcp4-server")
        self.assertEqual(self.dhcp(RESERVED_MAC), "192.168.50.10")
        self.assertEqual(self.dhcp("02:00:00:00:00:77"), ip)
        # 11. stop disables only the managed service
        self.assertFalse(service.stop(self.paths, self.ops, self.runner)["active"])


if __name__ == "__main__":
    unittest.main()
