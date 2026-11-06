import unittest

from dhcp_gui import i18n


class I18nTest(unittest.TestCase):
    def test_every_catalog_has_the_english_keys(self):
        expected = set(i18n.CATALOG["en"])
        self.assertEqual(set(i18n.CATALOG["it"]), expected)

    def test_language_comes_from_the_environment(self):
        self.assertEqual(i18n.current_language({"LANG": "it_IT.UTF-8"}), "it")

    def test_unknown_language_falls_back_to_english(self):
        self.assertEqual(i18n.current_language({"LANG": "ja_JP.UTF-8"}), "en")

    def test_unknown_key_returns_the_key(self):
        self.assertEqual(i18n.translate("no_such_key", "en"), "no_such_key")


if __name__ == "__main__":
    unittest.main()
