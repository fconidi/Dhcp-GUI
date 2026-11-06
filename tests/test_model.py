import json
import unittest

from dhcp_gui.core import model
from dhcp_gui.core.model import DhcpConfig, Reservation, Subnet, ValidationError


def sub(**kw):
    base = dict(id=1, interface="eth1", server_ip="192.168.50.1", subnet="192.168.50.0/24",
                pool_start="192.168.50.100", pool_end="192.168.50.200")
    base.update(kw)
    return Subnet(**base)


def code(config):
    with unittest.TestCase().assertRaises(ValidationError) as cm:
        model.validate(config)
    return cm.exception.code


class ModelTest(unittest.TestCase):
    def test_valid_config_renders_deterministically(self):
        cfg = DhcpConfig([sub(gateway="192.168.50.254", dns=["1.1.1.1"], domain="lan.example",
                              reservations=[Reservation("hw-address", "AA-BB-CC-DD-EE-01", "192.168.50.10")])])
        first = model.render(cfg)
        self.assertEqual(first, model.render(cfg))
        data = json.loads(first)["Dhcp4"]
        self.assertEqual(data["interfaces-config"]["interfaces"], ["eth1/192.168.50.1"])
        self.assertEqual(data["subnet4"][0]["reservations"][0]["hw-address"], "aa:bb:cc:dd:ee:01")
        self.assertNotIn("hooks-libraries", data)

    def test_hook_is_only_the_fixed_lease_cmds_library(self):
        data = model.to_kea(DhcpConfig([sub()], lease_cmds=True))["Dhcp4"]
        self.assertEqual(data["hooks-libraries"], [{"library": model.HOOK_LEASE_CMDS}])

    def test_pool_outside_subnet(self):
        self.assertEqual(code(DhcpConfig([sub(pool_end="192.168.51.5")])), "outside_subnet")

    def test_server_inside_pool(self):
        self.assertEqual(code(DhcpConfig([sub(server_ip="192.168.50.150")])), "server_in_pool")

    def test_gateway_inside_pool(self):
        self.assertEqual(code(DhcpConfig([sub(gateway="192.168.50.101")])), "gateway_in_pool")

    def test_network_address_rejected(self):
        self.assertEqual(code(DhcpConfig([sub(pool_start="192.168.50.0")])), "outside_subnet")

    def test_non_strict_subnet_rejected(self):
        self.assertEqual(code(DhcpConfig([sub(subnet="192.168.50.1/24")])), "bad_subnet")

    def test_reservation_rules(self):
        r = lambda ip, mac="aa:bb:cc:dd:ee:01": Reservation("hw-address", mac, ip)
        self.assertEqual(code(DhcpConfig([sub(reservations=[r("192.168.50.150")])])), "reservation_in_pool")
        self.assertEqual(code(DhcpConfig([sub(reservations=[r("10.0.0.5")])])), "outside_subnet")
        self.assertEqual(code(DhcpConfig([sub(reservations=[r("192.168.50.1")])])), "reservation_conflict")
        self.assertEqual(code(DhcpConfig([sub(reservations=[r("192.168.50.10"), r("192.168.50.11")])])),
                         "duplicate_identifier")
        self.assertEqual(code(DhcpConfig([sub(reservations=[r("192.168.50.10"), r("192.168.50.10", "aa:bb:cc:dd:ee:02")])])),
                         "duplicate_ip")
        self.assertEqual(code(DhcpConfig([sub(reservations=[r("192.168.50.10", "zz")])])), "bad_mac")

    def test_client_id_identifier(self):
        cfg = DhcpConfig([sub(reservations=[Reservation("client-id", "01:AA:bb:cc:dd:ee:02", "192.168.50.12")])])
        self.assertEqual(model.to_kea(cfg)["Dhcp4"]["subnet4"][0]["reservations"][0]["client-id"],
                         "01:aa:bb:cc:dd:ee:02")

    def test_boot_file_allows_paths_but_not_control_chars(self):
        model.validate(DhcpConfig([sub(boot_file="pxelinux/lpxelinux.0", next_server="192.168.50.2")]))
        self.assertEqual(code(DhcpConfig([sub(boot_file="a\nb")])), "control_chars")
        self.assertEqual(code(DhcpConfig([sub(boot_file="a" * 129)])), "too_long")

    def test_domain_and_dns(self):
        self.assertEqual(code(DhcpConfig([sub(domain="bad domain")])), "bad_domain")
        self.assertEqual(code(DhcpConfig([sub(dns=["1.1.1.1"] * 5)])), "too_many_dns")
        self.assertEqual(code(DhcpConfig([sub(dns=["nope"])])), "bad_ip")

    def test_multi_subnet_checks(self):
        other = sub(id=2, interface="eth2", server_ip="192.168.60.1", subnet="192.168.60.0/24",
                    pool_start="192.168.60.10", pool_end="192.168.60.20")
        model.validate(DhcpConfig([sub(), other]))
        self.assertEqual(code(DhcpConfig([sub(), sub(id=1, interface="eth2", subnet="10.0.0.0/24",
                                                     server_ip="10.0.0.1", pool_start="10.0.0.5", pool_end="10.0.0.9")])),
                         "duplicate_subnet_id")
        self.assertEqual(code(DhcpConfig([sub(), sub(id=2)])), "duplicate_interface")
        self.assertEqual(code(DhcpConfig([sub(), sub(id=2, interface="eth2", subnet="192.168.50.0/25",
                                                     server_ip="192.168.50.2", pool_start="192.168.50.5",
                                                     pool_end="192.168.50.9")])), "subnet_overlap")

    def test_interface_name_is_restricted(self):
        self.assertEqual(code(DhcpConfig([sub(interface="eth0/1.2.3.4")])), "bad_interface")
        self.assertEqual(code(DhcpConfig([sub(interface="../x")])), "bad_interface")

    def test_lifetime_bounds(self):
        self.assertEqual(code(DhcpConfig([sub(valid_lifetime=5)])), "bad_lifetime")

    def test_ids_are_kept_and_output_sorted_by_id(self):
        a = sub(id=7)
        b = sub(id=3, interface="eth2", server_ip="10.0.0.1", subnet="10.0.0.0/24",
                pool_start="10.0.0.5", pool_end="10.0.0.9")
        ids = [s["id"] for s in model.to_kea(DhcpConfig([a, b]))["Dhcp4"]["subnet4"]]
        self.assertEqual(ids, [3, 7])


if __name__ == "__main__":
    unittest.main()
