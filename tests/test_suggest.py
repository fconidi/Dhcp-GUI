import ipaddress
import unittest

from dhcp_gui.core import model, suggest
from dhcp_gui.core.model import DhcpConfig, Subnet


def build(s, gw=""):
    return DhcpConfig([Subnet(1, "eth1", s.server_ip, s.subnet, s.pool_start, s.pool_end, gateway=gw)])


class SuggestTest(unittest.TestCase):
    def check(self, addr, gw=""):
        s = suggest.suggest(addr, gw)
        model.validate(build(s, gw))
        return s

    def test_various_prefixes_validate(self):
        for addr in ("192.168.50.1/24", "10.0.0.5/16", "172.16.4.200/25", "192.168.1.2/29", "10.1.1.1/30"):
            self.check(addr)

    def test_not_a_fixed_range(self):
        a, b = self.check("192.168.50.1/24"), self.check("10.0.0.1/22")
        self.assertNotEqual(a.pool_start.split(".")[-1], b.pool_start.split(".")[-1])

    def test_gateway_and_server_stay_out_of_the_pool(self):
        s = self.check("192.168.50.150/24", "192.168.50.254")
        pool = range(int(ipaddress.IPv4Address(s.pool_start)), int(ipaddress.IPv4Address(s.pool_end)) + 1)
        self.assertNotIn(int(ipaddress.IPv4Address("192.168.50.150")), pool)
        self.assertNotIn(int(ipaddress.IPv4Address("192.168.50.254")), pool)

    def test_bad_prefix(self):
        with self.assertRaises(ValueError):
            suggest.suggest("10.0.0.1/31")


if __name__ == "__main__":
    unittest.main()
