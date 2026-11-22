# Owner L2TP/IPsec VPN

Settings → VPN connects the installed AirLink Linux PC to an L2TP/IPsec server using a username, password and pre-shared key. Only the `owner` role can read status, save settings, connect, disconnect or remove the profile. Settings permissions granted to managers do not grant VPN access.

Enter the VPN server's IPv4 address or hostname (without a URL), username, password and IPsec shared key. Add the remote IPv4 subnets you need, for example `192.168.88.0/24`. Save, then connect. The status and assigned VPN IPv4 address update silently every five seconds. Disconnect before changing or removing settings. Blank secret fields preserve saved values. Connect/disconnect are manual; automatic startup/reconnect is not included.

AirLink manages only its reserved NetworkManager profile. The default route and DNS remain on the existing network; IPv6 is disabled on this VPN profile. Remote routes must not conflict with the local management LAN. This connects the AirLink PC, not other LAN clients. Failed authentication does not fall back to unencrypted L2TP.

Credentials are sent to NetworkManager through system D-Bus and stored in its root-readable system connection file. They are not returned by the API or included in command-line arguments or audit events. Root administrators can read the file. Standard installed-system backups already include `/etc/NetworkManager/system-connections`; review network settings locally before restoring connectivity.

The ISO recipe includes `network-manager-l2tp` and `strongswan`. Existing installations need those packages before using the feature; application-only/offline updates do not provision them. From the installed PC's root recovery shell:

```sh
apt-get update
apt-get install --no-install-recommends network-manager-l2tp strongswan
```

The macOS local preview displays this page but cannot create a Linux VPN tunnel. Enter real credentials on the installed AirLink PC. A live connection still requires a reachable server and matching credentials, which are not provided with the application.

Implementation references: [NetworkManager connection settings and secrets](https://networkmanager.dev/docs/api/latest/gdbus-org.freedesktop.NetworkManager.Settings.Connection.html), [NetworkManager L2TP plugin](https://github.com/nm-l2tp/NetworkManager-l2tp).
