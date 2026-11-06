import hashlib
import os
import tempfile
import unittest

from dhcp_gui.core import apply as ap
from dhcp_gui.core import service
from tests.test_apply import ApplyBase, FakeOps, cfg


class ServiceTest(ApplyBase):
    def managed(self):
        self.make(FakeOps(active=False)).apply(cfg(), self.token())

    def test_start_and_stop_refuse_unmanaged_instances(self):
        for fn in (service.start, service.stop):
            ops = FakeOps()
            with self.assertRaises(ap.ApplyError) as cm:
                fn(self.paths, ops, self.runner)
            self.assertEqual(cm.exception.code, "not_managed")
            self.assertFalse(any(c.startswith("systemctl") for c in ops.calls))

    def test_start_enables_and_stop_disables_only_when_managed(self):
        self.managed()
        ops = FakeOps(active=True)
        self.assertTrue(service.start(self.paths, ops, self.runner)["active"])
        self.assertIn("systemctl enable --now kea-dhcp4-server", ops.calls)
        ops = FakeOps(active=False)
        service.stop(self.paths, ops, self.runner)
        self.assertIn("systemctl disable --now kea-dhcp4-server", ops.calls)

    def test_start_failure_is_reported(self):
        self.managed()
        ops = FakeOps(active=False)
        with self.assertRaises(ap.ApplyError):
            service.start(self.paths, ops, self.runner)      # unit never becomes active

    def test_stats_percentages(self):
        answer = [{"result": 0, "arguments": {
            "subnet[1].total-addresses": [[101, "t"]], "subnet[1].assigned-addresses": [[25, "t"]],
            "subnet[1].declined-addresses": [[0, "t"]], "subnet[1].pool[0].assigned-addresses": [[25, "t"]],
            "pkt4-received": [[1, "t"]]}}]
        out = service.stats(lambda c, a=None: answer)
        self.assertEqual(out["subnets"], [{"subnet_id": 1, "total": 101, "assigned": 25, "declined": 0, "percent": 24.8}])

    def test_stats_without_socket(self):
        with self.assertRaises(ap.ApplyError) as cm:
            service.stats(lambda c, a=None: None)
        self.assertEqual(cm.exception.code, "unavailable")

    def test_leases_require_the_command_and_are_paged(self):
        def no_hook(c, a=None):
            return [{"result": 0, "arguments": ["list-commands"]}] if c == "list-commands" else None
        with self.assertRaises(ap.ApplyError) as cm:
            service.leases("start", 10, no_hook)
        self.assertIn("lease_cmds", cm.exception.detail)

        def hook(c, a=None):
            if c == "list-commands":
                return [{"result": 0, "arguments": ["lease4-get-page"]}]
            return [{"result": 0, "arguments": {"leases": [
                {"ip-address": "192.168.50.100", "hw-address": "aa:bb", "cltt": 100, "valid-lft": 50, "subnet-id": 1},
                {"ip-address": "192.168.50.101", "hw-address": "cc:dd", "cltt": 100, "valid-lft": 50, "subnet-id": 1}]}}]
        out = service.leases("start", 2, hook)
        self.assertEqual((len(out["leases"]), out["next"], out["leases"][0]["expire"]), (2, "192.168.50.101", 150))
        with self.assertRaises(ap.ApplyError):
            service.leases("1.2.3.999", 2, hook)

    def test_empty_lease_page_is_not_an_error(self):
        def hook(c, a=None):
            if c == "list-commands":
                return [{"result": 0, "arguments": ["lease4-get-page"]}]
            return [{"result": 3, "text": "0 IPv4 lease(s) found."}]
        self.assertEqual(service.leases("start", 5, hook), {"leases": [], "next": ""})


if __name__ == "__main__":
    unittest.main()


class CurrentAndAdoptionTest(ApplyBase):
    def test_current_returns_managed_model_and_apply_can_adopt_importable(self):
        import json
        from dhcp_gui.helper import daemon
        from dhcp_gui.core import protocol, model
        # a custom but supported file -> importable -> adoption through apply
        open(self.paths.debian_conf, "w").write("// mine\n" + model.render(cfg()))
        self.md5 = "0" * 32
        cur = json.loads(daemon.handle(protocol.encode_request("current"), self.paths, self.runner))
        self.assertEqual(cur["data"]["state"], "importable")
        res = self.make(FakeOps(active=False)).apply(cfg("192.168.50.210"), self.token())
        self.assertTrue(res.ok)
        cur = json.loads(daemon.handle(protocol.encode_request("current"), self.paths, self.runner))
        self.assertEqual(cur["data"]["state"], "managed")
        self.assertEqual(cur["data"]["model"]["subnets"][0]["pool_end"], "192.168.50.210")
