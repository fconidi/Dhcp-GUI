import unittest

from dhcp_gui.core import kea_import, model
from dhcp_gui.core.model import DhcpConfig, Reservation, Subnet


def cfg():
    return DhcpConfig([
        Subnet(1, "eth1", "192.168.50.1", "192.168.50.0/24", "192.168.50.100", "192.168.50.200",
               gateway="192.168.50.254", dns=["1.1.1.1", "9.9.9.9"], domain="lan.example",
               next_server="192.168.50.2", boot_file="pxelinux/lpxelinux.0", valid_lifetime=7200,
               reservations=[Reservation("hw-address", "aa:bb:cc:dd:ee:01", "192.168.50.10", "pc1"),
                             Reservation("client-id", "01:aa:bb:cc:dd:ee:02", "192.168.50.11")]),
        Subnet(2, "eth2", "10.9.0.1", "10.9.0.0/24", "10.9.0.50", "10.9.0.99")], lease_cmds=True)


class StripCommentsTest(unittest.TestCase):
    def test_comments_removed_but_not_inside_strings(self):
        text = '{ "a": "x // y # z /* q */", // c1\n # c2\n "b": 1 /* c3 */ }'
        self.assertEqual(kea_import.parse_text(text), {"a": "x // y # z /* q */", "b": 1})

    def test_trailing_commas_are_tolerated_like_kea(self):
        self.assertEqual(kea_import.parse_text('{ "a": [1, 2, // x\n ], "b": "x,}", }'), {"a": [1, 2], "b": "x,}"})

    def test_include_is_unsupported(self):
        with self.assertRaises(kea_import.Unsupported):
            kea_import.parse_text('{ <?include "x.json"?> }')

    def test_unterminated_comment(self):
        with self.assertRaises(kea_import.Unsupported):
            kea_import.parse_text("{ /* oops }")


class ImportTest(unittest.TestCase):
    def test_round_trip_of_generated_config(self):
        original = cfg()
        imported = kea_import.import_config(model.render(original))
        self.assertEqual(model.render(imported), model.render(original))

    def test_unknown_keys_make_it_unsupported(self):
        import json
        data = model.to_kea(cfg())
        data["Dhcp4"]["loggers"] = [{"name": "kea-dhcp4"}]
        data["Dhcp4"]["subnet4"][0]["relay"] = {"ip-addresses": ["1.2.3.4"]}
        data["Dhcp4"]["hooks-libraries"].append({"library": "/tmp/evil.so"})
        with self.assertRaises(kea_import.Unsupported) as cm:
            kea_import.import_config(json.dumps(data))
        joined = " | ".join(cm.exception.reasons)
        self.assertIn("Dhcp4.loggers", joined)
        self.assertIn("subnet4[0].relay", joined)
        self.assertIn("hook library", joined)

    def test_other_option_is_not_dropped_silently(self):
        import json
        data = model.to_kea(cfg())
        data["Dhcp4"]["subnet4"][0]["option-data"].append({"name": "ntp-servers", "data": "1.1.1.1"})
        with self.assertRaises(kea_import.Unsupported):
            kea_import.import_config(json.dumps(data))

    def test_stock_debian_file_is_not_importable(self):
        text = '''{ "Dhcp4": { "interfaces-config": { "interfaces": [ ] },
          "control-socket": { "socket-type": "unix", "socket-name": "kea4-ctrl-socket" },
          "lease-database": { "type": "memfile", "lfc-interval": 3600 },
          "option-data": [ { "name": "domain-name-servers", "data": "192.0.2.1" } ],
          "subnet4": [ { "id": 1, "subnet": "192.0.2.0/24", "pools": [ { "pool": "192.0.2.10 - 192.0.2.20" } ] } ] } }'''
        with self.assertRaises(kea_import.Unsupported):
            kea_import.import_config(text)

    def test_interface_without_address_is_unsupported(self):
        import json
        data = model.to_kea(cfg())
        data["Dhcp4"]["interfaces-config"]["interfaces"] = ["eth1", "eth2/10.9.0.1"]
        with self.assertRaises(kea_import.Unsupported):
            kea_import.import_config(json.dumps(data))


if __name__ == "__main__":
    unittest.main()
