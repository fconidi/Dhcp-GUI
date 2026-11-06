"""Translations for every string shown to the user."""
import os

DEFAULT_LANGUAGE = "en"

CATALOG = {
    "en": {
        "app_title": "Dhcp-GUI",
        "app_subtitle": "Manage the Kea DHCPv4 server of this computer",
    },
    "it": {
        "app_title": "Dhcp-GUI",
        "app_subtitle": "Gestisci il server DHCPv4 Kea di questo computer",
    },
}


def current_language(environ=None) -> str:
    env = os.environ if environ is None else environ
    for name in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        for part in env.get(name, "").split(":"):
            code = part.split(".")[0].split("_")[0].lower()
            if code in CATALOG:
                return code
    return DEFAULT_LANGUAGE


def translate(key: str, language: str | None = None, **fields) -> str:
    lang = language if language in CATALOG else current_language()
    text = CATALOG[lang].get(key) or CATALOG[DEFAULT_LANGUAGE].get(key, key)
    return text.format(**fields) if fields else text
