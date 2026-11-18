# ISP card online device types

The **ISP card → Online users → Device type** column recognizes MikroTik, Ubiquiti (including M5/AC), Mimosa, Tenda, TP-Link, Ruijie / Reyee and Hikvision.

With automatic device readings enabled in **My account → Customer device access**, the background collector checks only device IP addresses supplied by the signed-in account's SAS4 online sessions. Results remain isolated by account, SAS4 connection, customer and session. Disabling automatic device readings stops both identity and telemetry probes.

- Configured read-only SNMP communities are tried using v2c and v1. The device's sysObjectID and sysDescr identify its manufacturer. Standard interface tables can provide Ethernet readings.
- If SNMP is unavailable or identifies only a generic device, AirLink checks public HTTPS/HTTP login-page branding. This requires no device password. The HTTP and TLS verification preferences still apply. The check has a four-second budget, sends no login credentials and does not follow redirects to other hosts, ports or protocols.
- Tenda, TP-Link, Ruijie / Reyee and Hikvision have brand recognition and standard SNMP support. Their proprietary web-login, configuration, SSID and radio-signal APIs are not implemented. Identifying their public branding does not trigger password attempts through the MikroTik/Ubiquiti adapters.
- When only the brand is available, the Device type column shows it, while missing speed/signal/SSID readings remain unavailable. A generic router title or an ambiguous model such as “AC1200” remains **Unknown / Generic**. A manufacturer name does not establish whether the hardware is a router, switch or camera.
- Devices that do not expose branding, have no accessible management service, or fail the configured TLS checks can remain unknown. This is identification from device responses, not MAC-address guessing. No new ports or remote-management settings are enabled on customer devices.

The local preview must be running the current backend and rebuilt frontend to display these changes. No publication or software-version change is needed to refresh the local preview.

Enterprise identifiers are verified against the [IANA Private Enterprise Numbers registry](https://www.iana.org/assignments/enterprise-numbers/): Tenda 59646; TP-Link 11863 and 65855; Ruijie 4881; Hikvision 39165. See also [TP-Link SNMP documentation](https://www.tp-link.com/us/configuration-guides/configuring_snmp_rmon/).
