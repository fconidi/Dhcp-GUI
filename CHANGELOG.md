# Changelog

## 0.1.1

- Configuration files protected by Debian permissions can be unlocked through Polkit and managed in the interface.
- Wait for Kea's control socket after a service restart before deciding whether to restore the previous configuration.

## 0.1.0

- First release: guided configuration of a Kea DHCPv4 subnet with pool, gateway, DNS, domain, PXE options and static reservations.
- Preview, validated apply with automatic backup and restore, service start and stop, pool usage and lease list.
- Read-only mode for Kea configurations the app does not manage; adoption of supported custom configurations.
- Italian and English interface.
