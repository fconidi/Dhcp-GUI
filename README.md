# Dhcp-GUI

A graphical manager for the Kea DHCPv4 server of a Debian-based computer
(Debian 13, SysLinuxOS). Kea stays the DHCP engine and the system service;
Dhcp-GUI configures it without editing JSON.

## Features

- Detects Kea, its version, the service state and the network interfaces, and warns when
  another DHCP server is active on the computer or when an interface gets its address from DHCP.
- Guided setup of a subnet: interface, address pool, lease time, gateway, DNS servers, domain,
  PXE next server and boot file. Pool and addresses are suggested from the interface.
- Static reservations by MAC address or client identifier, checked against the pool and the subnet.
- Preview of the generated Kea configuration before applying.
- Safe apply: the configuration is checked by Kea, the previous files are backed up and
  restored automatically if anything fails. The service is never stopped by an error.
- Start and stop of the service with confirmation, pool usage and the lease list.
- Italian and English interface.

Configurations written by hand and not covered by the supported options are shown
read-only. A supported custom configuration can be adopted after confirmation; the original
Kea file is never modified (the app uses its own file in `/etc/kea/managed/`).

## Requirements

`kea-dhcp4-server`, Python 3.11+, GTK 3 and polkit. Installing the package pulls them in.
Kea's default configuration does not serve any network until you apply a subnet and start the service.

## Use

Start **Dhcp-GUI** from the SysLinuxOS Tools menu, or run `dhcp-gui`. Reading the status needs
no password; reading statistics and leases asks for the administrator password once for a few
minutes; every change asks for it each time.

Make sure no other DHCP server is active on the same network before starting the service.

## Not included

DHCPv6, relay, high availability, dynamic DNS and database back ends.

## License

GPL-3.0-or-later.
