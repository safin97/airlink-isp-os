# Monitoring support

In **Settings → SNMP credential profiles → Add SNMP profile**, select the version supported by the device and create a profile. In **Towers**, edit the device, select its vendor and assign the profile. Enable SNMP on the device and allow UDP 161 from the AirLink server. Use a read-only community with source-address restrictions for v1/v2c. Profiles are owner-managed, stored encrypted and never returned with their secrets.

- **SNMP v2c:** community authentication; suitable for MikroTik, Mimosa and other devices whose firmware supports v2c.
- **SNMP v1:** explicit legacy option for airMAX M5/AC firmware. Ubiquiti documents read-only v1 support; choose the version your firmware actually supports.
- **SNMP v3:** authPriv with selectable SHA-1, SHA-256 or MD5 authentication and AES-128 or DES privacy. New profile forms default to SHA-1/AES-128 for RouterOS compatibility; existing profiles without protocol fields keep SHA-256/AES-128. Match the device’s configured username, protocols and keys. See the [RouterOS SNMP reference](https://help.mikrotik.com/docs/spaces/ROS/pages/8978519/SNMP).

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

Online-user Ethernet speed, signal and SSID are collected using **SNMP only**, independently of browser sessions. The saved SAS4 connection supplies the online-session list; customer device REST/web APIs are not contacted. The collector cycles through every online page. Four device probes run concurrently, each bounded to 33 seconds; successful results are cached for 30 seconds and failures for 120 seconds. Last reported readings stay visible during retries.

**My account → Customer device access** configures the read-only SNMP community. The owner can reuse saved inventory SNMP profiles; managers use their own community. Profiles accept version `2` as an alias for community-based v2c, which uses the SNMP v2 message processing model. Customer telemetry labels it SNMP v2; tower/device setup labels it SNMP v2c. Detection tries v1, v2 and then configured v3; incomplete v1 data does not stop the v2 attempt. v2 uses bounded GETBULK walks, falling back to GETNEXT if the agent rejects bulk requests.

Ethernet speed comes from active Ethernet interfaces in IF-MIB, preferring the named **ether1** port when present. Other devices show their actual Ethernet port names. MikroTik signal first uses the station-mode strength table (`1.3.6.1.4.1.14988.1.1.1.1.1.4`), with the registration table as fallback. Station SSID is `.1.1.1.1.1.5` under the MikroTik enterprise `1.3.6.1.4.1.14988`. Ubiquiti SSID uses `1.3.6.1.4.1.41112.1.4.5.1.2`. These mappings were checked against the official vendor MIBs linked above. Multiple ambiguous radio signals or SSIDs remain unavailable rather than selecting an arbitrary customer link.

The Connection column reports SNMP. Missing readings show **Checking…** during a check, then **Unavailable** if the device does not supply them. Cached readings are scoped by account, customer IP, session and credentials. Inventory data is reused only when fresh SNMP data is available and the account has access to that tower; API-only inventory readings are excluded.

On MikroTik, `trap-community=public` controls outgoing traps. Polling requires SNMP enabled, a `public` community with `read-access=yes` and UDP 161 access from AirLink. The software cannot obtain measurements from a device that does not answer SNMP. See the [RouterOS SNMP reference](https://help.mikrotik.com/docs/spaces/ROS/pages/8978519/SNMP).

## MikroTik switch Ethernet ports

In **Towers → devices → Add/Edit**, choose **MikroTik** and **MikroTik switch — SNMP v2c / public**, or a saved SNMPv2c profile with the switch's community. Enable SNMP polling on the switch and allow AirLink to reach UDP 161. The switch preset uses v2c only; existing radio profiles remain available.

Use the **Ethernet ports** action beside a MikroTik device to see every Ethernet interface reported by the bounded IF-MIB walk (up to 256 rows per table), including down and disabled ports and Ethernet SFP interfaces. Bridges, VLANs and wireless interfaces are excluded. Names come from ifName/ifDescr, type from ifType, disabled state from ifAdminStatus, and link state from ifOperStatus. Link up means connected; link down does not prove a port has never been used. Missing status stays unknown.

Receive/transmit Mbps are from the switch's perspective and averaged over two polls. Counter64 is preferred, with existing conservative Counter32 fallback; first samples, counter resets/wraps, reboots and ambiguous deltas show unavailable. Missing rates are never substituted with zero. Stale, disabled or failed SNMP readings do not appear as current traffic. The view refreshes stored readings every 15 seconds without triggering extra switch polls and uses existing tower read permissions. No API credentials or switch configuration writes are required.

References: [IF-MIB, RFC 2863](https://www.rfc-editor.org/info/rfc2863/) and [MikroTik SwOS CRS3xx/CSS3xx SNMP support](https://help.mikrotik.com/docs/spaces/SWOS/pages/76415036/CRS3xx%20and%20CSS3xx%20series%20Manual). Real switch firmware may expose fewer fields; unavailable data stays unavailable.

## Tower device API access

**Registration clients** displays **PPPoE username** in place of the radio interface column. MikroTik API inventory polling optionally matches `/ppp/active` PPPoE `caller-id` MACs to registration MACs; denied PPP read permission leaves radio monitoring available. Unmatched registrations can be matched to the viewing account's SAS4 active sessions when it has ISP Card access and a saved SAS4 connection. Only exact normalized MAC matches with one distinct username are shown; interface names, station names and neighboring MACs are never treated as usernames. Different radio/PPPoE MACs or multiple usernames on one MAC remain unavailable.

SAS4 matching is performed in the background, cached for 30 seconds per account and credential revision, and refreshed by the existing five-second registration dialog refresh. Incomplete/failed lookups do not supply names; unrelated customers are not returned. Lookups are bounded to two concurrent accounts and 10,000 active-session records. The local preview uses the real SAS4 lookup for this feature, without demo username mappings. Source: [MikroTik PPP active-session fields](https://help.mikrotik.com/docs/spaces/ROS/pages/132350049/PPP%2BAAA).

**Towers API** in the sidebar manages named, encrypted device login profiles. Add a name, username, password, HTTP/HTTPS connection and optional port; the owner can share a profile with selected managers. These profiles use the same saved-login library as **Device login**. Passwords are never returned; a blank password on edit preserves the saved password. Shared profiles can be used but only their owner can edit or delete them.

In **Towers → devices → Login device**, explicitly choose a saved profile and connect. This opens a read-only device overview through the existing MikroTik RouterOS REST or Ubiquiti airOS API adapter. The server obtains the IP from the authorized inventory device. Both tower access and profile access are checked on each connection/refresh; no ISP Card/SAS4 session is needed. Towers read permission allows connecting; profile creation/edit/deletion follows the corresponding Towers permissions. The device must expose a supported API and accept the selected credentials. Opening the full device web interface remains a separate browser session and may require logging in again. This selection does not change the tower's background monitoring credentials described below.

The owner can enable API monitoring in **Towers → Add tower / Edit tower**. Enter the read-only device username and password shared by that tower's devices, choose HTTPS or explicitly HTTP, and optionally set a custom web-service port (default 443/80). HTTPS certificate verification is enabled by default; turn it off only when intentionally using a device's untrusted local certificate. A blank password while editing preserves the encrypted saved password. Disable API monitoring to stop using those credentials. Managers can edit their assigned tower inventory but cannot read or replace its API credentials.

Every enabled inventory device inherits its tower's API settings and is polled at its device polling interval, alongside ICMP and any assigned SNMP profile. The API adapter supports **MikroTik RouterOS REST** (`/rest`, not the native TCP API on 8728/8729) and **Ubiquiti airOS M5/AC** (`login.cgi` / `status.cgi`). For RouterOS, enable the REST web service and provide a user with read/API permissions. For automatic vendor recognition, the device web page must identify RouterOS or airOS; alternatively set the device's vendor explicitly.

The tower device table shows API status, the active port named ether1, wireless SSIDs, registration client count and uptime when the device supplies them. CPU and memory columns are hidden there. Clicking the registration count opens a permission-scoped list of connected clients with MAC address, PPPoE username, SSID and signal; the dialog reads the latest collected records every five seconds and labels unavailable or stale lists. Lists are limited to 256 records and show the reported total when larger. MikroTik and Ubiquiti SNMP registration indexes provide MAC/interface identity; supported device APIs provide sanitized registration records. SSIDs include MikroTik AP-mode tables as well as station-mode tables. If a device has no active port named ether1, that column remains unavailable rather than displaying another port as ether1. Model and firmware appear in metric tooltips. AP station signal is labelled **Weakest**; it is not assigned to a particular subscriber. Unavailable fields remain unavailable; stale samples are hidden. API failure does not discard successful SNMP readings. Authentication failures are shown separately from general API connectivity failures. Credentials never appear in responses, metrics or audit records.

The local preview now runs the inventory monitoring loop against its existing inventory and preserves its database. Installed systems continue to use the existing `airlink-monitor` service. No scanning or device configuration writes are performed by API polling.

Adapter field references: [RouterOS REST](https://manual.mikrotik.com/docs/developer-guides/rest-api/), [RouterOS resource fields](https://help.mikrotik.com/docs/spaces/ROS/pages/40992875/Resource), and [airOS status response reported on Ubiquiti Community](https://community.ui.com/questions/AirOS-BUG-Breaks-APs-Web-GUI-when-Associated-Station-Supplies-INVALID-Data/21b93456-1611-49a6-922c-fc378b82d879).


## Dashboard PC performance

The dashboard PC performance section shows only four cards: CPU utilization and current clock, RAM usage, system-volume storage usage, and disk read/write activity. GPU, network and uptime readings are hidden from this section. A shared background sampler measures counters roughly every three seconds; the existing dashboard refresh updates the cards every 30 seconds without reloading the page. These are observed rates, not speed-test benchmarks. Network rates are shown per interface to avoid double-counting bridged traffic. First samples, counter resets, unsupported sensors and stale readings do not become zero values.

NVIDIA metrics use the existing PCI/nvidia-smi detector and require a working driver. Other detected GPUs remain visible with unavailable unsupported metrics. The macOS local preview reports its own host performance, not a remote installed AirLink PC. No privileged commands, router changes or external telemetry services are used.

## Places and towers

In **Towers**, the owner can select **Add place** and enter a name. Opening a place shows its tower cards; **Add tower** preselects that place. The main Towers page shows only places. Tower cards and **Add tower** appear after opening a named place. Existing towers without a place remain accessible through the **Unassigned towers** group, where the owner can assign a place in **Edit tower**. Each tower belongs to at most one place. Opening a tower still shows its devices, and returning preserves the selected place. Places can be renamed; move or remove their towers before deleting a place. Managers and technicians see only places containing towers they can already access, with counts scoped to that access. Grouping does not change inventory permissions or monitoring settings.

## Automatic device vendor detection

New devices default to Auto detect (SNMP / API); existing Generic devices also use this mode. SNMP sysObjectID/sysDescr and authenticated RouterOS/airOS responses identify supported vendors. Ubiquiti M5/AC is shown only when the identity contains a matching model; otherwise it remains Ubiquiti. Unknown identities remain generic. Configured SNMP profiles or tower API credentials are required; ping alone does not identify a vendor. Manual vendor selections remain available. Detection is displayed after polling and retained through temporary probe failures, but cleared when the device address/configuration changes.

## PC connection measurements

PC Performance includes ICMP round-trip latency to Google DNS (8.8.8.8) and an explicitly labeled gaming connection reference (1.1.1.1). The latter is not a PUBG Mobile or Call of Duty server measurement. Two shared, bounded probes run in parallel every five seconds; requests read their cache. Failed or blocked ICMP displays No reply, never a fabricated zero. System TX/RX and individual Ethernet cards are hidden from the dashboard. Network counters remain available to the monitoring service.


## Online user device detection

The API service starts a background customer collector at boot. It uses saved SAS4 connections for active accounts with ISP Card access and customer probing enabled; no browser or logged-in web session is required. It rotates through all online-user pages in batches of seven, with a five-second pause between batches and bounded device concurrency. A full queue delays the next batch, and upstream failures back off for one minute. Collection speed depends on device response times and the number of online users. Disabling Customer device access stops new background collection for that account.

The dashboard shares the collector's account- and session-scoped in-memory cache. Last reported Ethernet and signal readings remain visible while new checks run and through temporary failures, with a tooltip identifying retained data. New readings replace them. The cache is rebuilt after an API restart; it does not invent readings for devices that fail to respond.

Online users automatically tries the configured communities with SNMP v1 first, then v2c, followed by saved SNMP v3 credentials. A complete v1 response ends the sequence; incomplete v1 readings also try v2. v3 is never attempted with a guessed username or key. Owners can supply v3 credentials through Settings → SNMP credential profiles; global inventory secrets remain unavailable to other managers.

Device type identifies MikroTik, Ubiquiti (including recognizable M5/AC models), and Mimosa using SNMP sysObjectID/sysDescr. Mimosa's enterprise identifier 43356 is listed in the [IANA enterprise registry](https://www.iana.org/assignments/enterprise-numbers/). Online users no longer checks public device web pages; vendor identification there requires an SNMP identity response. Identification alone does not supply Ethernet speed or wireless signal. Mimosa identity and standard interface data are supported; vendor-specific Mimosa radio signal MIBs are not collected.

## Tower SNMP discovery

The owner can use **Towers → Tower actions → Discovery SNMP** to discover the tower management subnet (/24 through /32). This reads SNMP identity directly and does not require ping replies. It identifies MikroTik, Ubiquiti M5/AC and Mimosa from their enterprise OID/description; unknown SNMP devices remain Generic. Discovery uses configured v1, v2 and v3 profiles, plus public v2/v1, or one selected profile. v3 needs a saved username and authentication/privacy settings; discovery does not guess credentials or enable device services.

Each request checks up to 32 addresses with a 25-second per-address limit. The dialog shows progress, supports stopping between batches and reports incomplete checks. Select a specific profile if more than 16 profiles are saved. Scanning does not add inventory. **Add** or **Add all** creates devices with the detected vendor and matching profile; public profiles are encrypted and reused by protocol version. Existing inventory addresses are marked and skipped. Saved credential access and profile assignment remain owner-only; the existing ping discovery action retains its original permissions.

Owners can choose an SNMP profile directly in Add/Edit Device. The selector refreshes saved profiles when opened and explicitly includes **Mimosa — SNMP v2c / public**. Existing MikroTik, Ubiquiti (M5/AC/other), and Mimosa v1/v2c presets remain available; choose a version supported by the radio's firmware. The presets use the community `public`; this is a preset value, not an assumption about the radio's configured community. Presets share/reuse matching encrypted credentials and are assigned only when Save is clicked; choosing a preset does not change the device vendor. Saved custom-community and SNMP v3 profiles remain selectable. Devices must have matching SNMP read access enabled; a vendor preset does not imply every model exposes every vendor-specific metric.

For a Mimosa radio, open **Towers → your tower → Add device** or **Edit**, choose **Vendor → Mimosa**, and select **Mimosa — SNMP v2c / public** if the radio uses that community. For another community, first create a named **SNMP v2c** profile under **Settings → SNMP profiles**, then select that profile in the device form. Saving an unrelated device edit preserves its assigned profile. The device and profile screens display both stored version `2c` and the legacy `2` alias as **SNMP v2c**.

Tower **Discovery SNMP** includes Mimosa and MikroTik replies on v2c. Ubiquiti discovery uses v1; configured v3 profiles retain all detected vendors. Mimosa standard uptime/interface monitoring is supported; this change does not add proprietary wireless signal OIDs or prove reachability to a physical radio.

Automatic SNMP discovery also tries the other community protocol version for saved v1/v2 communities. A detected fallback retains its source profile reference; Add creates or reuses an encrypted profile for the version that actually answered. Private communities are never sent to the browser or replaced with public. Selecting one explicit profile still tests that profile only. Vendor and responding version remain visible after adding a device. A response proves that version works with those credentials, not that other versions are disabled; v3 requires saved credentials.

**Manage device** is available in tower device actions and for added discovery results. It opens wireless SSID settings and the collected registration-client list. MikroTik RouterOS REST supports explicit per-interface SSID changes for local wireless, wifi and wifiwave2 interfaces, using the tower API login. The device user needs write permission. Inherited/controller-managed settings and unrecognized interfaces are read-only. AirLink checks the previous SSID before writing, serializes changes per device, validates 1–32 UTF-8 bytes, sends only the chosen SSID field, and audits requests/results without credentials. Apply can disconnect clients; no device writes happen on opening the panel. Uncertain write outcomes are reported without retrying. Managers need Towers edit permission and access to that device's tower; read-only users can view permitted data. UBNT/Mimosa SSID writes are not implemented; their available registration/SSID telemetry remains viewable.

Configuration adapter references: [RouterOS REST API](https://manual.mikrotik.com/docs/developer-guides/rest-api/) and [Wi-Fi interface configuration](https://manual.mikrotik.com/docs/wireless/wifi/).

Owners can use **Settings → Device API logins** to choose a tower or a manager from their connected SAS4 account and save a device username/password, protocol, port and TLS verification setting. Tower assignments share the encrypted tower API configuration used by monitoring and Manage device. ISP Card manager assignments are encrypted inside the owner's customer settings, keyed by the SAS4 connection identity and manager ID; they are stored for device-management use, but online-user API controls are not added in this change. Changing the SAS4 login does not reuse another connection's assignments. The panel never reads back passwords, blank passwords preserve an existing login, and a changed username requires a new password. Existing SAS4 account passwords and SNMP-only customer collection are preserved. No schema migration is needed.

Device API connections can use **HTTPS + HTTP (auto)**. Monitoring and wireless management try HTTPS first and fall back to HTTP when the read connection/API is unavailable. A blank port uses 443 for HTTPS and 80 for HTTP; an explicit port applies to both. Rejected credentials do not trigger another login over HTTP, and an uncertain SSID write is never retried over a different protocol. Existing HTTPS-only and HTTP-only selections are preserved. The combined selection can also be stored for an ISP Card manager.
