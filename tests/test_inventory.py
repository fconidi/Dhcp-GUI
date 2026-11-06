import hashlib
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from dhcp_gui.core import inventory, model
from dhcp_gui.core.model import DhcpConfig, Subnet
from dhcp_gui.core.paths import Paths

IP_JSON = json.dumps([
    {"ifname": "lo", "flags": ["LOOPBACK", "UP"], "operstate": "UNKNOWN", "addr_info": [{"family": "inet", "local": "127.0.0.1", "prefixlen": 8}]},
    {"ifname": "eth0", "flags": ["BROADCAST", "UP"], "operstate": "UP",
     "addr_info": [{"family": "inet", "local": "192.168.1.5", "prefixlen": 24, "dynamic": True}]},
    {"ifname": "eth1", "flags": ["BROADCAST", "UP"], "operstate": "UP",
     "addr_info": [{"family": "inet", "local": "192.168.50.1", "prefixlen": 24}]},
    {"ifname": "eth2", "flags": ["BROADCAST"], "operstate": "DOWN", "addr_info": []},
])
DEBIAN_TEXT = '{ "Dhcp4": { "interfaces-config": { "interfaces": [ ] } } }'


class FakeRunner:
    def __init__(self, installed=True, md5=None, active="inactive"):
        self.installed, self.md5, self.active = installed, md5, active

    def __call__(self, cmd, timeout=5):
        if cmd[0] == "dpkg-query" and "${Conffiles}\\n" in " ".join(cmd):
            return (0, f" /etc/kea/kea-dhcp4.conf {self.md5}\n") if self.md5 else (1, "")
        if cmd[0] == "dpkg-query":
            return (0, "install ok installed|2.6.3-1+deb13u1") if self.installed else (1, "")
        if cmd[:2] == ["systemctl", "is-active"]:
            return 3, self.active + "\n"
        if cmd[:2] == ["systemctl", "is-enabled"]:
            return 0, "enabled\n"
        if cmd[0] == "ip":
            return 0, IP_JSON
        return 127, ""


class InventoryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.paths = Paths(self.tmp.name)
        os.makedirs(self.paths.proc + "/net")
        with open(self.paths.proc + "/net/udp", "w") as fh:
            fh.write("  sl  local_address rem_address st\n")

    def write(self, path, text):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            fh.write(text)

    def sha(self, path):
        return hashlib.sha256(open(path, "rb").read()).hexdigest()

    def test_nics_skip_loopback_and_flag_dynamic(self):
        nics = {n.name: n for n in inventory.parse_nics(IP_JSON)}
        self.assertEqual(set(nics), {"eth0", "eth1", "eth2"})
        self.assertFalse(nics["eth0"].stable)
        self.assertTrue(nics["eth1"].stable)
        self.assertEqual(nics["eth1"].addresses, ["192.168.50.1/24"])

    def test_kea_missing(self):
        inv = inventory.collect(self.paths, FakeRunner(installed=False))
        self.assertEqual(inv.config_state, "kea_missing")
        self.assertFalse(inv.kea_installed)
        self.assertEqual(len(inv.nics), 3)

    def test_pristine_debian_file_is_recognised_by_dpkg_hash(self):
        self.write(self.paths.debian_conf, DEBIAN_TEXT)
        md5 = hashlib.md5(DEBIAN_TEXT.encode()).hexdigest()
        inv = inventory.collect(self.paths, FakeRunner(md5=md5))
        self.assertEqual((inv.config_state, inv.writable), ("pristine", True))
        self.assertEqual(inv.kea_version, "2.6.3-1+deb13u1")

    def test_modified_debian_file_that_is_not_importable_is_read_only(self):
        self.write(self.paths.debian_conf, '{ "Dhcp4": { "loggers": [] } }')
        inv = inventory.collect(self.paths, FakeRunner(md5="0" * 32))
        self.assertEqual((inv.config_state, inv.writable), ("unsupported", False))
        self.assertTrue(inv.reasons)

    def test_modified_debian_file_with_supported_subset_is_importable_not_writable(self):
        cfg = DhcpConfig([Subnet(1, "eth1", "192.168.50.1", "192.168.50.0/24", "192.168.50.100", "192.168.50.200")])
        self.write(self.paths.debian_conf, "// mine\n" + model.render(cfg))
        inv = inventory.collect(self.paths, FakeRunner(md5="0" * 32))
        self.assertEqual((inv.config_state, inv.writable), ("importable", False))

    def test_unreadable_debian_file_requires_privileged_inventory(self):
        inv = inventory.Inventory(kea_installed=True)
        with patch.object(inventory, "is_pristine_debian", return_value=False), \
             patch("builtins.open", side_effect=PermissionError("denied")):
            inventory._classify(inv, self.paths, FakeRunner())
        self.assertEqual((inv.config_state, inv.writable), ("unreadable", False))

    def test_managed_state_requires_matching_hashes(self):
        self.write(self.paths.managed_conf, "{}")
        self.write(self.paths.dropin, "[Service]\n")
        state = {"format": 1, "files": {self.paths.managed_conf: self.sha(self.paths.managed_conf),
                                        self.paths.dropin: self.sha(self.paths.dropin)}}
        self.write(self.paths.state, json.dumps(state))
        inv = inventory.collect(self.paths, FakeRunner(md5="0" * 32))
        self.assertEqual((inv.config_state, inv.writable), ("managed", True))
        self.write(self.paths.managed_conf, "{ }")  # edited outside the app
        inv = inventory.collect(self.paths, FakeRunner(md5="0" * 32))
        self.assertEqual((inv.config_state, inv.writable), ("managed_modified", False))

    def test_managed_file_without_state_is_read_only(self):
        self.write(self.paths.managed_conf, "{}")
        inv = inventory.collect(self.paths, FakeRunner())
        self.assertEqual((inv.config_state, inv.writable), ("managed_modified", False))

    def test_other_dhcp_servers_detected_by_process_and_port(self):
        self.write(self.paths.proc + "/123/comm", "dnsmasq\n")
        self.write(self.paths.proc + "/124/comm", "kea-dhcp4\n")
        self.assertEqual(inventory.other_dhcp_servers(self.paths), ["dnsmasq"])
        os.remove(self.paths.proc + "/123/comm")
        self.write(self.paths.proc + "/net/udp", "  sl local\n   0: 00000000:0043 00000000:0000 07\n")
        self.assertEqual(inventory.other_dhcp_servers(self.paths), ["udp/67"])

    def test_inventory_never_contains_file_contents(self):
        self.write(self.paths.debian_conf, '{ "Dhcp4": { "password": "s3cret", "loggers": [] } }')
        text = json.dumps(inventory.collect(self.paths, FakeRunner(md5="0" * 32)).to_dict())
        self.assertNotIn("s3cret", text)


if __name__ == "__main__":
    unittest.main()
