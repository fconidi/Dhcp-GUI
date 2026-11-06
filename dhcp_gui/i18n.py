"""Translations for every string shown to the user."""
import os

DEFAULT_LANGUAGE = "en"

CATALOG = {
    "en": {
        "app_title": "Dhcp-GUI",
        "app_subtitle": "Manage the Kea DHCPv4 server of this computer",
        "kea_status": "Kea DHCPv4",
        "kea_missing": "Kea is not installed. Install the kea-dhcp4-server package to continue.",
        "kea_version": "Version {version}",
        "service_state": "Service: {active} (at boot: {enabled})",
        "nics_title": "Network interfaces",
        "nic_stable": "static address",
        "nic_dynamic": "address from DHCP: not suitable for a server",
        "nic_no_address": "no IPv4 address",
        "nic_down": "down",
        "other_dhcp": "Another DHCP server is active on this computer: {names}.",
        "state_pristine": "Kea is installed with the default configuration. DHCP-GUI can configure it.",
        "state_managed": "Configuration managed by DHCP-GUI.",
        "state_managed_modified": "The managed files were changed outside DHCP-GUI. Read-only mode.",
        "state_importable": "A custom configuration exists. It can be adopted after confirmation. Read-only for now.",
        "state_unsupported": "The Kea configuration uses features DHCP-GUI does not manage. Read-only mode.",
        "refresh": "Refresh",
        "helper_error": "The helper could not be started.",
    },
    "it": {
        "app_title": "Dhcp-GUI",
        "app_subtitle": "Gestisci il server DHCPv4 Kea di questo computer",
        "kea_status": "Kea DHCPv4",
        "kea_missing": "Kea non è installato. Installa il pacchetto kea-dhcp4-server per continuare.",
        "kea_version": "Versione {version}",
        "service_state": "Servizio: {active} (all'avvio: {enabled})",
        "nics_title": "Interfacce di rete",
        "nic_stable": "indirizzo statico",
        "nic_dynamic": "indirizzo da DHCP: non adatto a un server",
        "nic_no_address": "nessun indirizzo IPv4",
        "nic_down": "inattiva",
        "other_dhcp": "Un altro server DHCP è attivo su questo computer: {names}.",
        "state_pristine": "Kea è installato con la configurazione predefinita. DHCP-GUI può configurarlo.",
        "state_managed": "Configurazione gestita da DHCP-GUI.",
        "state_managed_modified": "I file gestiti sono stati modificati fuori da DHCP-GUI. Modalità sola lettura.",
        "state_importable": "Esiste una configurazione personalizzata. Si può adottare dopo conferma. Per ora sola lettura.",
        "state_unsupported": "La configurazione di Kea usa funzioni che DHCP-GUI non gestisce. Modalità sola lettura.",
        "refresh": "Aggiorna",
        "helper_error": "Impossibile avviare l'helper.",
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
