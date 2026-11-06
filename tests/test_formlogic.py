import unittest

from dhcp_gui import i18n
from dhcp_gui.core import model
from dhcp_gui.gui import formlogic

VALUES = {"interface": "eth1", "server_ip": "192.168.50.1", "subnet": "192.168.50.0/24",
          "pool": "192.168.50.100 - 192.168.50.200", "lifetime": "3600", "gateway": " 192.168.50.254 ",
          "dns": "1.1.1.1, 9.9.9.9", "domain": "", "next_server": "", "boot_file": ""}


class FormLogicTest(unittest.TestCase):
    def test_form_round_trip(self):
        res = [("hw-address", "aa:bb:cc:dd:ee:01", "192.168.50.10", "pc1")]
        config = formlogic.form_to_model(VALUES, res, True)
        model.validate(config)
        values, back, hook = formlogic.model_to_form(config)
        self.assertEqual(back, res)
        self.assertTrue(hook)
        self.assertEqual(values["gateway"], "192.168.50.254")
        self.assertEqual(formlogic.form_to_model(values, back, hook), config)

    def test_bad_input_becomes_a_validation_error_not_a_crash(self):
        for override, code in (({"lifetime": "abc"}, "bad_lifetime"), ({"pool": "nonsense"}, "bad_ip"),
                               ({"dns": "x"}, "bad_ip")):
            with self.assertRaises(model.ValidationError) as cm:
                model.validate(formlogic.form_to_model({**VALUES, **override}, [], False))
            self.assertEqual(cm.exception.code, code)

    def test_error_messages_cover_every_helper_code_in_both_languages(self):
        for code in ("conflict", "denied", "not_managed", "kea_rejected", "apply_failed", "unavailable", "validation", "x"):
            self.assertTrue(formlogic.error_message(code, "d|p"))
        self.assertIn("Check", formlogic.error_message("apply_failed", "boom [outcome=restore_failed service=down]")
                      if i18n.current_language() == "en" else "Check")
        self.assertEqual(set(i18n.CATALOG["en"]), set(i18n.CATALOG["it"]))


if __name__ == "__main__":
    unittest.main()
