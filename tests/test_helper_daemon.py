import io
import json
import unittest

from dhcp_gui.core import protocol
from dhcp_gui.helper import daemon
from tests.test_model import sub
from dhcp_gui.core.model import DhcpConfig


def fake_runner(cmd, timeout=5):
    return 127, ""


class DaemonTest(unittest.TestCase):
    def reply(self, raw):
        return json.loads(daemon.handle(raw, runner=fake_runner))

    def test_ping_and_inventory(self):
        self.assertTrue(self.reply(protocol.encode_request("ping"))["data"]["pong"])
        data = self.reply(protocol.encode_request("inventory"))["data"]
        self.assertFalse(data["kea_installed"])

    def test_preview_returns_json_and_reports_validation_errors(self):
        good = self.reply(protocol.encode_request("preview", DhcpConfig([sub()])))
        self.assertIn("Dhcp4", json.loads(good["data"]["json"]))
        bad = self.reply(protocol.encode_request("preview", DhcpConfig([sub(pool_end="10.0.0.1")])))
        self.assertEqual(bad["error"]["code"], "validation")

    def test_unprivileged_process_refuses_privileged_operations(self):
        for op in ("service_stop", "stats", "restore", "current", "inventory_private"):
            raw = daemon.handle(protocol.encode_request(op), runner=fake_runner, allowed={"none"})
            self.assertEqual(json.loads(raw)["error"]["code"], "denied", op)
        raw = daemon.handle(protocol.encode_request("stats"), runner=fake_runner, allowed={"none", "read"})
        self.assertNotEqual(json.loads(raw).get("error", {}).get("code"), "denied")
        raw = daemon.handle(protocol.encode_request("service_stop"), runner=fake_runner, allowed={"none", "read"})
        self.assertEqual(json.loads(raw)["error"]["code"], "denied")

    def test_garbage_is_rejected_without_crash(self):
        self.assertEqual(self.reply(b"{not json")["error"]["code"], "bad_request")

    def test_serve_loop(self):
        out = io.BytesIO()
        daemon.serve(io.BytesIO(protocol.encode_request("ping") * 2), out)
        self.assertEqual(out.getvalue().count(b"pong"), 2)


if __name__ == "__main__":
    unittest.main()
