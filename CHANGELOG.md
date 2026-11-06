# Changelog

## 0.1.3

- Resolve the Kea lease hook path for the host Debian architecture.
- Keep configurations with multiple subnets read-only in the guided form, and preserve the ID of an existing single subnet.

## 0.1.2

- Redesigned window: status bar with the service state and the start/stop action, warnings shown where they matter, grouped settings with hints, interface list with clear badges, pool usage bars and lease list.
- Password prompts no longer freeze the window; settings are checked before asking for the password and the faulty field is highlighted.
- Follows the light or dark system theme.
- The menu entry now also uses the shared SysLinuxOS Tools folder definition.

## 0.1.1

- Configuration files protected by Debian permissions can be unlocked through Polkit and managed in the interface.
- Wait for Kea's control socket after a service restart before deciding whether to restore the previous configuration.

## 0.1.0

- First release: guided configuration of a Kea DHCPv4 subnet with pool, gateway, DNS, domain, PXE options and static reservations.
- Preview, validated apply with automatic backup and restore, service start and stop, pool usage and lease list.
- Read-only mode for Kea configurations the app does not manage; adoption of supported custom configurations.
- Italian and English interface.
