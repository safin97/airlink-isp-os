# Monitoring support

In **Settings → SNMP credential profiles → Add SNMP profile**, select the version supported by the device and create a profile. In **Towers**, edit the device, select its vendor and assign the profile. Enable SNMP on the device and allow UDP 161 from the AirLink server. Use a read-only community with source-address restrictions for v1/v2c. Profiles are owner-managed, stored encrypted and never returned with their secrets.

- **SNMP v2c:** community authentication; suitable for MikroTik and devices whose firmware supports v2c.
- **SNMP v1:** explicit legacy option for airMAX M5/AC firmware. Ubiquiti documents read-only v1 support; choose the version your firmware actually supports.
- **SNMP v3:** authPriv with SHA-256 and AES-128. Existing profiles retain v3 behavior. Firmware must support that exact combination.

ICMP echo is checked independently; a device is online when either ICMP or SNMP responds. Persistent failures cross the configured threshold before offline state. Availability reports specifically measure observed ICMP samples, so an ICMP-blocking device may have SNMP online status and 0% ICMP availability.

## Standard metrics

| Metric | MIB / OID |
|---|---|
| Uptime | sysUpTime.0, `1.3.6.1.2.1.1.3.0` |
| Interface names | ifName, `1.3.6.1.2.1.31.1.1.1.1`; fallback ifDescr, `1.3.6.1.2.1.2.2.1.2` |
| Link state | ifOperStatus, `1.3.6.1.2.1.2.2.1.8` |
| Speed | ifHighSpeed, `1.3.6.1.2.1.31.1.1.1.15`; fallback ifSpeed, `1.3.6.1.2.1.2.2.1.5` |
| 64-bit RX / TX | ifHCInOctets / ifHCOutOctets, `.31.1.1.1.6` / `.31.1.1.1.10` under `1.3.6.1.2.1` |
| 32-bit RX / TX | ifInOctets / ifOutOctets, `.2.2.1.10` / `.2.2.1.16` under `1.3.6.1.2.1` |
| Counter discontinuity | ifCounterDiscontinuityTime, `1.3.6.1.2.1.31.1.1.1.19` |
| CPU load | hrProcessorLoad, `1.3.6.1.2.1.25.3.3.1.2` |
| RAM | hrStorageType/AllocationUnits/Size/Used, entries explicitly typed hrStorageRam |

Sources: [RFC 3418](https://www.rfc-editor.org/rfc/rfc3418), [RFC 2863](https://www.rfc-editor.org/rfc/rfc2863), [RFC 2790](https://www.rfc-editor.org/rfc/rfc2790).

## MikroTik and Ubiquiti radio adapters

Select **MikroTik**, **Ubiquiti airMAX M5** or **Ubiquiti airMAX AC** on the device. Existing Ubiquiti entries use the same airMAX adapter. Generic/Mimosa entries continue standard monitoring.

| Vendor | Metric | Table column OID |
|---|---|---|
| MikroTik | Registered clients per AP interface | `1.3.6.1.4.1.14988.1.1.1.3.1.6` |
| MikroTik | Radio frequency (MHz) | `1.3.6.1.4.1.14988.1.1.1.3.1.7` |
| MikroTik | Registered-station signal (dBm) | `1.3.6.1.4.1.14988.1.1.1.2.1.3` |
| airMAX M5 / AC | Station count per wireless interface | `1.3.6.1.4.1.41112.1.4.5.1.15` |
| airMAX M5 / AC | Radio frequency (MHz) | `1.3.6.1.4.1.41112.1.4.1.1.4` |
| airMAX M5 / AC | Wireless signal (dBm) | `1.3.6.1.4.1.41112.1.4.5.1.5` |
| airMAX M5 / AC | Noise floor (dBm) | `1.3.6.1.4.1.41112.1.4.5.1.8` |

Mappings were checked against the [official MikroTik MIB](https://download.mikrotik.com/routeros/7.25/mikrotik.mib) (2026-09-01 revision) and [Ubiquiti airOS MIB bundle](https://www.ui.com/downloads/firmwares/airos-ubnt-mib/ubnt-mib.zip) (`UBNT-AirMAX-MIB`, 2017-10-03 revision). Configuration references: [MikroTik SNMP](https://help.mikrotik.com/docs/spaces/ROS/pages/8978519/SNMP), [Ubiquiti airMAX SNMP](https://help.ui.com.cn/articles/210391987/).

Monitoring displays the sum of reported radio client counts, weakest reported signal and distinct measured frequencies. Raw wireless tables retain their own indices in metrics; station indices are not assumed to match interface indices. These client counts are radio associations, not SAS4 users. Unsupported OIDs stay unavailable; an explicit zero client count remains zero. CPU, RAM and radio fields depend on hardware, operating mode and firmware (including RouterOS wireless driver packages). Configured sector frequency remains inventory metadata.

## Traffic and validation limits

Traffic rates require two valid samples with unchanged counter width/discontinuity and no uptime regression. Missing, reset or wrapped counters produce unavailable values. SNMPv1 skips Counter64 and uses 32-bit counters. For 32-bit counters, rates are omitted when link speed is unknown or the interval could contain a full wrap at link speed; use shorter polling intervals or v2c with Counter64 where supported. Rates are also omitted for the first sample after switching counter width.

The chart sums interfaces and may include traffic seen on both a bridge and member ports; it is not billing-grade throughput. Walks are bounded to 256 entries per table and 45 seconds overall. Large devices need a reviewed capacity/configuration change.

Automated fixtures exercise vendor MIB parsing, absent fields, v1 fallback and v3 compatibility. A disposable Net-SNMP agent checks protocol interoperability. Physical MikroTik/M5/AC hardware has not been tested in this change; unsupported firmware fields remain unavailable.

## ISP Card online-user link readings

Opening **ISP Card → Online users** automatically checks the IPs returned by that account's SAS4 online-session list. Customer devices no longer have to be added to tower inventory first. The API runs a bounded background probe pool, including in the local preview; it does not depend on the separate inventory monitoring worker. Four customer probes run concurrently, at most 128 are pending and each probe has a 25-second total deadline. Successes are cached for 30 seconds, failures for 120 seconds. The existing page refresh shows results without reloading the page. Only the currently requested online-user pages are queued; this is not an all-address network scan.

**My account → Customer device access** configures a shared read-only SNMP community and optional device API username/password for that manager's customers. These are device credentials, not SAS4 credentials. Secrets are encrypted and never returned. The owner can also reuse up to four saved inventory SNMP profiles; managers cannot reuse another account's profiles. Community profiles are tried as v2c then legacy v1; v3 profiles retain their exact configured authentication. Detection identifies MikroTik and Ubiquiti vendor OIDs. It does not guess passwords or enable remote services.

If SNMP does not supply both readings and device API credentials are configured, detection can use:

- **MikroTik RouterOS REST** on HTTPS 443: read Ethernet interfaces, run one-shot Ethernet monitor commands and read wireless/Wi-Fi registration tables. Requires RouterOS with REST enabled and an account authorized for these read operations. Native RouterOS TCP API ports 8728/8729 are not implemented by this adapter.
- **Legacy airOS M5/AC web status** on HTTPS 443: authenticate using the supplied device account and read `status.cgi`. This is firmware-dependent and is not the UniFi controller API. Station-mode signal only is used.

HTTPS certificate verification is on by default. Self-signed certificate support and HTTP 80 fallback are explicit settings. HTTP sends credentials without transport encryption, so enable it only on a trusted management network. Redirects are never followed, HTTP responses are capped at 1 MiB, and IP targets reject loopback, link-local, multicast, unspecified and reserved addresses. No DNS targets are accepted. Customer IPs must be reachable from the AirLink server, and the device must expose a supported service with matching credentials.

Readings are cached by signed-in manager, session, customer IP and credential configuration, so another manager/session cannot consume the cached result. Existing fresh inventory telemetry remains usable only within the user's tower permissions. Cache entries do not persist passwords or survive a restart.

Ethernet speed uses active Ethernet ports, not Wi-Fi capacity or Internet plan speed. SNMP identifies them with IANA `ethernetCsmacd(6)` through IF-MIB `ifType` (`1.3.6.1.2.1.2.2.1.3`, [RFC 2863](https://www.rfc-editor.org/rfc/rfc2863)). Multiple ports are labeled separately. Signal is shown only for an unambiguous customer radio reading; an AP's weakest-client summary is never substituted. The Connection column reports the authenticated source (SNMP version, RouterOS API or airOS API). Missing readings remain **Unavailable**, with a tooltip explaining credentials, pending checks, failed access or unsupported fields.

API references: [MikroTik REST](https://manual.mikrotik.com/docs/developer-guides/rest-api/), [Ethernet monitor](https://manual.mikrotik.com/docs/cli-reference/interface/ethernet/monitor/), and [the original airOS status/login example on Ubiquiti Community](https://community.ui.com/questions/Frequency-Signal-Checker-Script/dfa38a91-252d-4761-a88b-741a931fa948). Automated protocol fixtures validate the API adapters; compatibility still depends on actual device firmware and configuration.

The local customer checks also offer **Check SNMP with public community**, enabled by default. It tries `public` using v2c, then v1, before other configured credentials. Disable this option in Customer device access when it is not used on your network. These focused checks read Ethernet link status/speed and radio signal without CPU, storage or traffic-counter walks. MikroTik connections are identified in the Connection column. In RouterOS, `trap-community=public` selects outgoing trap credentials; polling also requires SNMP enabled, a `public` community with `read-access=yes`, and UDP 161 access from the AirLink server. Trap reception is not added by this option. See [MikroTik SNMP](https://help.mikrotik.com/docs/spaces/ROS/pages/8978519/SNMP).
