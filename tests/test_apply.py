import hashlib
import json
import os
import tempfile
import unittest

from dhcp_gui.core import apply as ap
from dhcp_gui.core import inventory, model
from dhcp_gui.core.model import DhcpConfig, Subnet
from dhcp_gui.core.paths import Paths

DEBIAN = '{ "Dhcp4": { "interfaces-config": { "interfaces": [ ] } } }'


def cfg(pool_end="192.168.50.200"):
    return DhcpConfig([Subnet(1, "eth1", "192.168.50.1", "192.168.50.0/24", "192.168.50.100", pool_end)])


class FakeOps(ap.SystemOps):
    def __init__(self, active=True):
        self.active, self.calls, self.fail = active, [], set()
        self.ctl_ok = True

    def _maybe(self, name):
        self.calls.append(name)
        if name in self.fail:
            raise ap.ApplyError("apply_failed", f"injected {name}")

    def run(self, cmd, timeout=30):
        return 127, ""

    def kea_test(self, path):
        self.calls.append("test")
        return ("test" not in self.fail), "rejected" if "test" in self.fail else ""

    def systemctl(self, *args):
        self.calls.append("systemctl " + " ".join(args))
        return ("systemctl " + " ".join(args)) not in self.fail

    def is_active(self):
        return self.active

    def ctl(self, command, arguments=None):
        self.calls.append("ctl " + command)
        if "ctl " + command in self.fail:
            return None
        return [{"result": 0}]

    def write_atomic(self, path, data, mode):
        n = sum(1 for c in self.calls if c.startswith("write"))
        self.calls.append("write " + os.path.basename(path))
        if f"write#{n}" in self.fail:
            raise OSError("injected write failure")
        super().write_atomic(path, data, mode)


class ApplyBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.paths = Paths(self.tmp.name)
        os.makedirs(os.path.dirname(self.paths.debian_conf))
        open(self.paths.debian_conf, "w").write(DEBIAN)
        self.md5 = hashlib.md5(DEBIAN.encode()).hexdigest()
        os.makedirs(self.paths.proc + "/net")

    def runner(self, cmd, timeout=5):
        if "${Conffiles}\\n" in " ".join(cmd):
            return 0, f" /etc/kea/kea-dhcp4.conf {self.md5}\n"
        if cmd[0] == "dpkg-query":
            return 0, "install ok installed|2.6.3"
        return 127, ""

    def make(self, ops):
        return ap.Applier(self.paths, ops, self.runner)

    def token(self):
        return inventory.collect(self.paths, self.runner).token

    def snapshot(self):
        out = {}
        for p in (self.paths.managed_conf, self.paths.dropin, self.paths.state):
            out[p] = open(p, "rb").read() if os.path.exists(p) else None
        return out


class ApplyTest(ApplyBase):
    def test_first_apply_on_pristine_active_service_restarts(self):
        ops = FakeOps(active=True)
        res = self.make(ops).apply(cfg(), self.token())
        self.assertEqual((res.ok, res.action), (True, "restart"))
        self.assertEqual(res.steps, ["INVENTORY", "VALIDATE", "TEST", "BACKUP", "WRITE_ATOMIC",
                                     "RELOAD_OR_START", "VERIFY", "COMMIT"])
        self.assertIn("systemctl restart kea-dhcp4-server", ops.calls)
        self.assertEqual(open(self.paths.debian_conf).read(), DEBIAN)       # Debian conffile untouched
        self.assertEqual(oct(os.stat(self.paths.managed_conf).st_mode & 0o777), "0o644")
        self.assertEqual(oct(os.stat(self.paths.state).st_mode & 0o777), "0o600")
        self.assertIn("-c /etc/kea/managed/kea-dhcp4.conf", open(self.paths.dropin).read())
        self.assertFalse(os.path.exists(self.paths.backups + "/IN_PROGRESS"))
        self.assertEqual(inventory.collect(self.paths, self.runner).config_state, "managed")

    def test_restart_waits_for_control_socket_to_be_ready(self):
        ops = FakeOps(active=True)
        original = ops.ctl
        attempts = {"n": 0}

        def delayed(command, arguments=None):
            if command == "status-get":
                attempts["n"] += 1
                if attempts["n"] < 3:
                    return None
            return original(command, arguments)

        ops.ctl = delayed
        result = self.make(ops).apply(cfg(), self.token())
        self.assertTrue(result.ok)
        self.assertEqual(result.action, "restart")
        self.assertEqual(attempts["n"], 3)

    def test_second_apply_prefers_config_reload(self):
        ops = FakeOps(active=True)
        self.make(ops).apply(cfg(), self.token())
        ops2 = FakeOps(active=True)
        res = self.make(ops2).apply(cfg("192.168.50.210"), self.token())
        self.assertEqual(res.action, "reload")
        self.assertIn("ctl config-reload", ops2.calls)
        self.assertNotIn("systemctl restart kea-dhcp4-server", ops2.calls)

    def test_inactive_service_is_not_started(self):
        ops = FakeOps(active=False)
        res = self.make(ops).apply(cfg(), self.token())
        self.assertEqual(res.action, "none")
        self.assertFalse(any("start" in c or "enable" in c for c in ops.calls))

    def test_stale_token_is_a_conflict_and_changes_nothing(self):
        token = self.token()
        open(self.paths.debian_conf, "w").write(DEBIAN + " ")
        before = self.snapshot()
        with self.assertRaises(ap.ApplyError) as cm:
            self.make(FakeOps()).apply(cfg(), token)
        self.assertEqual(cm.exception.code, "conflict")
        self.assertEqual(self.snapshot(), before)

    def test_file_changed_outside_after_apply_blocks_next_apply(self):
        self.make(FakeOps()).apply(cfg(), self.token())
        stale = self.token()
        open(self.paths.managed_conf, "a").write(" ")
        with self.assertRaises(ap.ApplyError) as cm:
            self.make(FakeOps()).apply(cfg(), stale)
        self.assertEqual(cm.exception.code, "conflict")
        with self.assertRaises(ap.ApplyError) as cm:
            self.make(FakeOps()).apply(cfg(), self.token())
        self.assertEqual(cm.exception.code, "not_managed")

    def test_invalid_model_and_rejected_by_kea_leave_files_untouched(self):
        before = self.snapshot()
        with self.assertRaises(ap.ApplyError) as cm:
            self.make(FakeOps()).apply(cfg("10.0.0.1"), self.token())
        self.assertEqual(cm.exception.code, "validation")
        ops = FakeOps()
        ops.fail.add("test")
        with self.assertRaises(ap.ApplyError) as cm:
            self.make(ops).apply(cfg(), self.token())
        self.assertEqual(cm.exception.code, "kea_rejected")
        self.assertEqual(self.snapshot(), before)
        self.assertFalse(os.path.exists(self.paths.backups))
        self.assertEqual(os.listdir(os.path.dirname(self.paths.managed_conf)), [])

    def test_unsupported_config_is_never_written(self):
        open(self.paths.debian_conf, "w").write('{ "Dhcp4": { "loggers": [] } }')
        self.md5 = "0" * 32
        with self.assertRaises(ap.ApplyError) as cm:
            self.make(FakeOps()).apply(cfg(), self.token())
        self.assertEqual(cm.exception.code, "not_managed")
        self.assertFalse(os.path.exists(self.paths.managed_conf))


class FaultInjectionTest(ApplyBase):
    def run_failing(self, fail, pre_applied=False):
        if pre_applied:
            self.make(FakeOps()).apply(cfg(), self.token())
        before = self.snapshot()
        ops = FakeOps(active=True)
        ops.fail.update(fail)
        with self.assertRaises(ap.ApplyError) as cm:
            self.make(ops).apply(cfg("192.168.50.220"), self.token())
        return before, cm.exception, ops

    def test_each_write_failing_restores_previous_files(self):
        for n in (0, 1, 2):
            with self.subTest(write=n):
                self.setUp()
                before, err, _ops = self.run_failing({f"write#{n + 1}"})
                self.assertEqual(err.code, "apply_failed")
                self.assertEqual(self.snapshot(), before)
                self.assertFalse(os.path.exists(self.paths.backups + "/IN_PROGRESS"))

    def test_restart_failure_restores_and_reports_service_state(self):
        before, err, ops = self.run_failing({"systemctl restart kea-dhcp4-server"})
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(err.code, "apply_failed")
        self.assertEqual(err.outcome, "restore_failed")       # restart keeps failing during reapply
        self.assertEqual(err.service, "active_uncertain")     # fake service reports active, state unproven

    def test_reload_failure_falls_back_to_restart_then_verifies(self):
        self.make(FakeOps()).apply(cfg(), self.token())
        ops = FakeOps()
        ops.fail.add("ctl config-reload")
        res = self.make(ops).apply(cfg("192.168.50.230"), self.token())
        self.assertEqual(res.action, "restart")

    def test_verify_failure_on_reload_path_restores_old_config(self):
        self.make(FakeOps()).apply(cfg(), self.token())
        before = self.snapshot()
        ops = FakeOps()
        calls = {"n": 0}
        original = ops.ctl

        def flaky(command, arguments=None):
            if command == "status-get":
                calls["n"] += 1
                if calls["n"] == 1:
                    return None
            return original(command, arguments)
        ops.ctl = flaky
        with self.assertRaises(ap.ApplyError) as cm:
            self.make(ops).apply(cfg("192.168.50.240"), self.token())
        self.assertEqual(self.snapshot(), before)
        self.assertEqual((cm.exception.outcome, cm.exception.service), ("restored", "active_old"))

    def test_service_down_after_failed_restore_is_reported_not_stopped(self):
        before, err, ops = self.run_failing({"systemctl restart kea-dhcp4-server"})
        ops2 = FakeOps(active=False)
        ops2.fail.update({"systemctl restart kea-dhcp4-server"})
        # service reported inactive after the failed reapply -> "down"
        calls = iter([True, False, False, False])
        ops2.is_active = lambda: next(calls, False)
        with self.assertRaises(ap.ApplyError) as cm:
            self.make(ops2).apply(cfg("192.168.50.221"), self.token())
        self.assertEqual(cm.exception.service, "down")
        self.assertFalse(any("stop" in c for c in ops2.calls))

    def test_restore_failure_is_declared(self):
        ops = FakeOps()
        ops.fail.add("write#2")
        original = ap.Applier._restore_files
        ap.Applier._restore_files = lambda self, bid: (_ for _ in ()).throw(OSError("disk"))
        try:
            with self.assertRaises(ap.ApplyError) as cm:
                self.make(ops).apply(cfg(), self.token())
        finally:
            ap.Applier._restore_files = original
        self.assertEqual((cm.exception.code, cm.exception.outcome), ("restore_failed", "restore_failed"))
        self.assertTrue(os.path.exists(self.paths.backups + "/IN_PROGRESS"))
        inv = inventory.collect(self.paths, self.runner)
        self.assertEqual((inv.config_state, inv.writable), ("managed_modified", False))

    def test_interrupted_change_can_be_restored(self):
        self.make(FakeOps()).apply(cfg(), self.token())
        good = self.snapshot()
        applier = self.make(FakeOps())
        bid = applier._backup()                                  # simulates a crash after BACKUP
        applier.ops.write_atomic(self.paths.managed_conf, b"{ broken", 0o644)
        res = self.make(FakeOps()).restore_last()
        self.assertEqual(res.outcome, "restored")
        self.assertEqual(self.snapshot(), good)
        self.assertFalse(os.path.exists(self.paths.backups + "/IN_PROGRESS"))

    def test_backups_are_private_and_pruned(self):
        applier = self.make(FakeOps())
        os.makedirs(self.paths.backups, exist_ok=True)
        for i in range(15):
            os.makedirs(f"{self.paths.backups}/2026010{i:02d}-000000-1")
        applier._backup()
        self.assertLessEqual(len(os.listdir(self.paths.backups)), ap.KEEP_BACKUPS + 1)
        self.assertEqual(oct(os.stat(self.paths.backups).st_mode & 0o777), "0o700")

    def test_concurrent_transaction_is_refused(self):
        import fcntl
        os.makedirs(os.path.dirname(self.paths.lock), exist_ok=True)
        with open(self.paths.lock, "a+") as held:
            fcntl.flock(held, fcntl.LOCK_EX)
            with self.assertRaises(ap.ApplyError) as cm:
                self.make(FakeOps()).apply(cfg(), self.token())
        self.assertEqual(cm.exception.code, "conflict")


if __name__ == "__main__":
    unittest.main()
