import json
import unittest

from dhcp_gui.core import protocol
from dhcp_gui.core.model import DhcpConfig, Reservation, Subnet, ValidationError
from dhcp_gui.core.protocol import ProtocolError


def cfg():
    return DhcpConfig([Subnet(1, "eth1", "192.168.50.1", "192.168.50.0/24", "192.168.50.100", "192.168.50.200",
                              reservations=[Reservation("hw-address", "aa:bb:cc:dd:ee:01", "192.168.50.10")])])


def req(**over):
    body = {"version": 1, "op": "ping", "args": {}}
    body.update(over)
    return json.dumps(body).encode()


class ProtocolTest(unittest.TestCase):
    def test_model_round_trip(self):
        op, args, model = protocol.parse_request(protocol.encode_request("preview", cfg()))
        self.assertEqual((op, args), ("preview", {}))
        self.assertEqual(model, cfg())

    def test_every_operation_has_an_authorization_class(self):
        for op, cls in protocol.OPERATIONS.items():
            self.assertIn(cls, ("none", "admin"), op)
        for op in ("apply", "restore", "service_start", "service_stop", "verify", "leases"):
            self.assertEqual(protocol.OPERATIONS[op], "admin", op)

    def test_unknown_operation_and_version(self):
        for raw, code in ((req(op="shell"), "unknown_operation"), (req(version=2), "bad_version")):
            with self.assertRaises(ProtocolError) as cm:
                protocol.parse_request(raw)
            self.assertEqual(cm.exception.code, code)

    def test_raw_kea_json_paths_and_commands_are_rejected(self):
        for extra in ({"kea": {"Dhcp4": {}}}, {"path": "/etc/passwd"}, {"command": "id"}):
            with self.assertRaises(ProtocolError):
                protocol.parse_request(req(**extra))
        with self.assertRaises(ProtocolError):
            protocol.parse_request(req(op="ping", args={"unit": "ssh.service"}))

    def test_hooks_cannot_be_smuggled_in_the_model(self):
        data = protocol.model_to_dict(cfg())
        data["hooks_libraries"] = [{"library": "/tmp/evil.so"}]
        with self.assertRaises(ProtocolError):
            protocol.parse_request(req(op="preview", model=data))
        data = protocol.model_to_dict(cfg())
        data["subnets"][0]["library"] = "/tmp/evil.so"
        with self.assertRaises(ProtocolError):
            protocol.parse_request(req(op="preview", model=data))

    def test_wrong_types_are_rejected(self):
        data = protocol.model_to_dict(cfg())
        data["subnets"][0]["id"] = True
        with self.assertRaises(ProtocolError):
            protocol.parse_request(req(op="preview", model=data))
        data = protocol.model_to_dict(cfg())
        data["subnets"][0]["dns"] = [1]
        with self.assertRaises(ProtocolError):
            protocol.parse_request(req(op="preview", model=data))

    def test_model_required_only_where_needed(self):
        with self.assertRaises(ProtocolError):
            protocol.parse_request(req(op="apply"))
        with self.assertRaises(ProtocolError):
            protocol.parse_request(req(op="ping", model={"subnets": []}))

    def test_size_limit(self):
        with self.assertRaises(ProtocolError) as cm:
            protocol.parse_request(b"x" * (protocol.MAX_REQUEST_BYTES + 1))
        self.assertEqual(cm.exception.code, "too_large")

    def test_leases_limit_is_bounded(self):
        protocol.parse_request(req(op="leases", args={"limit": 50}))
        for bad in (0, 5000, True):
            with self.assertRaises(ProtocolError):
                protocol.parse_request(req(op="leases", args={"limit": bad}))

    def test_responses(self):
        self.assertTrue(json.loads(protocol.ok(a=1))["ok"])
        err = json.loads(protocol.error("nonsense"))
        self.assertEqual(err["error"]["code"], "internal")
        v = json.loads(protocol.validation_error(ValidationError("bad_ip", "subnets[0].dns[1]", "x")))
        self.assertEqual(v["error"]["code"], "validation")
        self.assertEqual(v["error"]["path"], "subnets[0].dns[1]")
        big = json.loads(protocol.ok(blob="x" * (protocol.MAX_RESPONSE_BYTES + 1)))
        self.assertEqual(big["error"]["code"], "too_large")


if __name__ == "__main__":
    unittest.main()
