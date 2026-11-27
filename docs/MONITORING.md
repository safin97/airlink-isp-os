# Monitoring support

In **Settings → SNMP credential profiles → Add SNMP profile**, select the version supported by the device and create a profile. In **Towers**, edit the device, select its vendor and assign the profile. Enable SNMP on the device and allow UDP 161 from the AirLink server. Use a read-only community with source-address restrictions for v1/v2c. Profiles are owner-managed, stored encrypted and never returned with their secrets.

- **SNMP v2c:** community authentication; suitable for MikroTik, Mimosa and other devices whose firmware supports v2c.
- **SNMP v1:** explicit legacy option for airMAX M5/AC firmware. Ubiquiti documents read-only v1 support; choose the version your firmware actually supports.
- **SNMP v3:** authPriv with selectable SHA-1, SHA-256 or MD5 authentication and AES-128 or DES privacy. New profile forms default to SHA-1/AES-128 for RouterOS compatibility; existing profiles without protocol fields keep SHA-256/AES-128. Match the device’s configured username, protocols and keys. See the [RouterOS SNMP reference](https://help.mikrotik.com/docs/spaces/ROS/pages/8978519/SNMP).

ICMP echo is checked independently; a device is online when either ICMP or SNMP responds. Persistent failures cross the configured threshold before offline state. Availability reports specifically measure observed ICMP samples, so an ICMP-blocking device may have SNMP online status and 0% ICMP availability.

## Device downtime history

After a device reports readings, its last known SSID, signal, Ethernet speed, client count and reported uptime stay visible during an outage. The full device row turns red, downtime increases while monitoring confirms the outage, and uptime stays frozen at the last reported value. **Last known readings** identifies retained data; hover over a reading for its local collection time. New successful readings replace the corresponding values, including zero client counts and a lower uptime after reboot. Missing fields retain their own previous collection times. Last known client counts can open the retained client list, where unconfirmed statuses are labelled Unknown.

Display snapshots persist across page refreshes, server restarts, metric retention and device settings changes. They are separate from live samples and are not used to fabricate monitoring charts or alerts. A device must report data before it has a snapshot. Settings changes restart live monitoring while keeping previous display values marked as last known. When a saved reading was collected at a different address, its tooltip identifies that address. Deleting the device removes its saved readings.

An empty or partial SNMP walk does not erase a saved SSID or ether1 speed. If other ports respond but ether1 has no new speed, the inventory keeps ether1's last measured speed and collection time. A reported registration-client count of zero is valid and is retained too. Failed probes cannot replace saved readings with empty defaults. Fields that have never been reported remain unavailable.

Open **Towers → a tower → a device's Downtime history button** (clock icon in Actions). The same button is available when opening tower devices from the NOC Screen. Each row shows the date and local 24-hour clock time the device went down, when it came back online, and its total downtime in minutes and seconds. The latest 100 completed outages are shown, newest first, plus any confirmed ongoing outage marked **Still down**. The view refreshes every 15 seconds and remains available while the device is offline; it does not require a device API login.

An outage is confirmed after the configured failure threshold. Its start is the first failed monitoring check and its end is the first successful recovery check, so accuracy depends on the device's polling interval. Brief failures below the threshold are not recorded as outages. Completed records remain saved after recovery and telemetry cleanup. An ongoing duration is shown only while monitoring readings are fresh and the device is enabled; stopping monitoring does not establish continued downtime. History uses the existing tower access scope and is readable with Towers, NOC Screen or Monitoring access.

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

Select **MikroTik**, **Ubiquiti airMAX M5** or **Ubiquiti airMAX AC** on the device. Existing Ubiquiti entries use the same airMAX adapter. Generic entries continue standard monitoring. Mimosa has the additional support described below.

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

### Mimosa device rows

Choosing **Mimosa** replaces Wireless SSID with **Signal** and Registration clients with **TX / RX traffic** in the device inventory, including devices opened from Towers or NOC. Automatically detected Mimosa devices use the same view. Mixed-vendor lists label both kinds of readings. Ethernet speed is displayed beside the actual reported port name, including names such as `eth0`, independently of traffic-counter availability. Automatic chooses one available Ethernet link for the row; click the reading to inspect all reported ports. Traffic still prefers `ether1` or a single unambiguous Ethernet interface; it never sums bridge/radio traffic.

Mimosa/C5c Ethernet speed uses standard IF-MIB `ifHighSpeed` (Mbps), falling back to `ifSpeed` (bits per second, converted to Mbps) when the high-speed value is absent or zero. Only reported up, enabled Ethernet interfaces supply new speed readings. Missing speed, a partial poll or an outage keeps the last measured speed and its original collection time, marked as retained. The current Ethernet-port list continues to show current link state separately. Mimosa's vendor-authored [BASE MIB, revision 3.00](https://raw.githubusercontent.com/librenms/librenms/master/mibs/mimosa/MIMOSA-NETWORKS-BASE-MIB) identifies C5c and references IF-MIB for Ethernet speed changes; trap-history values and wireless PHY rates are not used as live Ethernet speed. C5c regression fixtures cover the standard fallback and retained readings; physical-radio verification is still required.

The collector reads Mimosa's measured total receive power (`mimosaTotalRxPower`, `1.3.6.1.4.1.43356.2.1.2.6.6.0`). If absent, it uses the weakest reported PTMP client RSSI (`mimosaPtmpClientRssiAvg`, column `1.3.6.1.4.1.43356.2.1.2.9.6.1.1.11`), identified in the signal tooltip. Both use tenths of dBm. Mappings come from Mimosa's vendor-authored [BFIVE MIB, revision 1.02](https://raw.githubusercontent.com/librenms/librenms/master/mibs/mimosa/MIMOSA-NETWORKS-BFIVE-MIB) and [PTMP MIB, revision 0.3](https://raw.githubusercontent.com/librenms/librenms/master/mibs/mimosa/MIMOSA-NETWORKS-PTMP-MIB), mirrored by LibreNMS. Firmware/model variants without these objects remain unavailable; target signal and PHY rates are not substituted for measured readings.

TX/RX are the selected Ethernet port's measured traffic in Mbps, from the device's perspective. Rates require two valid monitoring samples. A measured zero remains zero; missing rates remain unavailable. Stale/failed samples and down ports do not retain healthy-looking traffic readings. Existing live inventory updates carry these values without a page reload. No physical Mimosa device has been used for validation.

### Counter handling

Traffic rates require two valid samples with unchanged counter width/discontinuity and no uptime regression. Missing, reset or wrapped counters produce unavailable values. SNMPv1 skips Counter64 and uses 32-bit counters. For 32-bit counters, rates are omitted when link speed is unknown or the interval could contain a full wrap at link speed; use shorter polling intervals or v2c with Counter64 where supported. Rates are also omitted for the first sample after switching counter width.

The chart sums interfaces and may include traffic seen on both a bridge and member ports; it is not billing-grade throughput. Walks are bounded to 256 entries per table and 45 seconds overall. Large devices need a reviewed capacity/configuration change.

Automated fixtures exercise vendor MIB parsing, absent fields, v1 fallback and v3 compatibility. A disposable Net-SNMP agent checks protocol interoperability. Physical MikroTik/M5/AC hardware has not been tested in this change; unsupported firmware fields remain unavailable.

## ISP Card online-user link readings

Online-user Ethernet speed, signal and SSID are collected using **SNMP only**, independently of browser sessions. The saved SAS4 connection supplies the online-session list; customer device REST/web APIs are not contacted. The collector cycles through every online page. Four device probes run concurrently, each bounded to 33 seconds; successful results are cached for 30 seconds and failures for 120 seconds. Last reported readings stay visible during retries.

**My account → Customer device access** configures the read-only SNMP community. The owner can reuse saved inventory SNMP profiles; managers use their own community. Profiles accept version `2` as an alias for community-based v2c, which uses the SNMP v2 message processing model. Customer telemetry labels it SNMP v2; tower/device setup labels it SNMP v2c. Detection tries v1, v2 and then configured v3; incomplete v1 data does not stop the v2 attempt. v2 uses bounded GETBULK walks, falling back to GETNEXT if the agent rejects bulk requests.

Ethernet speed comes from active Ethernet interfaces in IF-MIB, preferring the named **ether1** port when present. Other devices show their actual Ethernet port names. MikroTik signal first uses the station-mode strength table (`1.3.6.1.4.1.14988.1.1.1.1.1.4`), with the registration table as fallback. Station SSID is `.1.1.1.1.1.5` under the MikroTik enterprise `1.3.6.1.4.1.14988`. Ubiquiti SSID uses `1.3.6.1.4.1.41112.1.4.5.1.2`. These mappings were checked against the official vendor MIBs linked above. Multiple ambiguous radio signals or SSIDs remain unavailable rather than selecting an arbitrary customer link.

The Connection column reports SNMP. Missing readings show **Checking…** during a check, then **Unavailable** if the device does not supply them. Cached readings are scoped by account, customer IP, session and credentials. Inventory data is reused only when fresh SNMP data is available and the account has access to that tower; API-only inventory readings are excluded.

On MikroTik, `trap-community=public` controls outgoing traps. Polling requires SNMP enabled, a `public` community with `read-access=yes` and UDP 161 access from AirLink. The software cannot obtain measurements from a device that does not answer SNMP. See the [RouterOS SNMP reference](https://help.mikrotik.com/docs/spaces/ROS/pages/8978519/SNMP).

## Wireless client connection history

The Registration clients column shows confirmed **Online** and **Offline** counts and an **Unknown** count when status cannot be confirmed. Counts cover retained, known clients; unsupported history does not invent offline counts. Click the counts to view known clients, including disconnected clients. The list offers **Stable row order**, **Online first** and **Offline first**; status groups preserve first-seen order internally, and Unknown stays separate. Each MAC retains its first-seen row position across refreshes, reconnects and service restarts; newly observed clients append to the end (MAC order within each new batch). Online means the latest successful check reported the client. Offline requires a complete registration list that no longer contains it. Failed, stale, partial or truncated checks show Unknown for clients whose status cannot be confirmed. Device outages do not prove an individual wireless disconnection. Last seen, SSID and signal remain visible, and down rows turn red. Hover over status for its transition time or last confirmed state.

History is stored with the device's telemetry snapshot, separately from raw monitoring samples. It retains up to 4,096 distinct MAC addresses per device and reports when that limit is reached. Address edits preserve history but leave old-address clients unconfirmed until seen at the new address. Polls collect at most 256 registration entries; incomplete lists never mark absent clients down. These statuses require a supported registration source; vendor identity or a client count alone cannot supply individual client history.

## Ruijie / Reyee RG-EST450G

Manual Ruijie/Reyee selection and automatic detection use the same tower view. The table displays the actual names and measured speeds of active Ethernet interfaces from IF-MIB, including ports whose names are not `ether1`. SSID and signal have separate readings in the same column; registration counts retain the usual client-list action. Last known readings remain visible during outages with their original collection times.

The [official Reyee MIB package](https://www.ruijie.com/en-global/resources/preview/reyee-mib/) documents standard interface tables. Its instruction manual specifies the generic Net-SNMP sysObjectID `1.3.6.1.4.1.8072.3.2.10`; that OID alone cannot identify Reyee. An explicit `RG-EST450G` model in sysDescr can identify this bridge, as can the Ruijie/Reyee brand. The package reviewed does not document SSID, RSSI or wireless registration OIDs. AirLink does not yet have a verified wireless collector for this model, so those fields remain unavailable until a supported source supplies them. Display tests use synthetic fixtures; physical RG-EST450G validation is pending device access.

## Device Ethernet ports

To choose the port shown in a device row's **ether1 speed / Ethernet speed** column, click that reading, select **Port shown in the Ethernet speed column**, then **Save displayed port**. Available choices include reported SNMP Ethernet/SFP ports (including down ports), API-reported links and retained port readings. **Automatic (available port)** chooses a port with a valid, positive speed from the latest poll: it prefers `ether1`, otherwise keeps its current port while available, then chooses another reported port in name order. When no new speed is available, it retains the last automatically chosen port and its original collection time. Explicit selections remain fixed until you choose Automatic. The preference is saved per device and shared with all viewers; changing it requires tower-edit access and does not change the radio configuration, polling or client order.

A selected port shows only its own measured speed. If it stops reporting, its last speed remains visible with that port's collection time; another port's new reading does not make it fresh. A port with no recorded speed shows Unavailable. Port history retains up to 256 names per device. Migration `e97ab6038214` preserves existing devices with Automatic selected. An unrelated device edit preserves the selected port.

In **Towers → devices → Add/Edit**, choose **MikroTik** and **MikroTik switch — SNMP v2c / public**, or a saved SNMPv2c profile with the switch's community. Enable SNMP polling on the switch and allow AirLink to reach UDP 161. The switch preset uses v2c only; existing radio profiles remain available.

Click the **Ethernet speed** (or **ether1 speed**) reading in a device row to see every Ethernet interface reported by the bounded IF-MIB walk (up to 256 rows per table), including down and disabled ports and Ethernet SFP interfaces. This works across vendors, including Ruijie/Reyee, Ubiquiti and Mimosa, with SNMPv1, v2c or v3 profiles. The cell remains clickable when its speed is unavailable. Devices without an SNMP profile show setup guidance. The existing MikroTik switch management action opens the same list. Bridges, VLANs and wireless interfaces are excluded. Names come from ifName/ifDescr, type from ifType, disabled state from ifAdminStatus, and link state from ifOperStatus. Link up means connected; link down does not prove a port has never been used. Missing status stays unknown.

Receive/transmit Mbps are from the device's perspective and averaged over two polls. Counter64 is preferred, with existing conservative Counter32 fallback; first samples, counter resets/wraps, reboots and ambiguous deltas show unavailable. Missing rates are never substituted with zero. Stale, disabled or failed SNMP readings do not appear as current traffic. The view refreshes stored readings every 5 seconds without triggering extra device polls and uses existing tower read permissions. No API credentials or switch configuration writes are required.

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

The dashboard PC performance section shows CPU utilization and current clock, GPU utilization, RAM usage, system-volume storage usage, disk read/write activity and connection latency. Each GPU appears beside CPU with a usage percentage and progress bar, model, VRAM, temperature and driver details. A valid usage reading shows Working · Active above zero or Working · Idle at zero. Missing drivers and unavailable utilization remain explicit and do not show a working state or a zero usage bar. A shared background sampler measures counters roughly every three seconds; the existing dashboard refresh updates the cards every 30 seconds without reloading the page. First samples, counter resets, unsupported sensors and stale readings do not become zero values.

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

## Online users and registration usernames before login

The API service starts account-scoped SAS4 session collection at startup; it does not require an active web login. A scheduler runs every five seconds and refreshes each eligible saved SAS4 account about every 30 seconds, with two concurrent account fetches and a 60-second retry delay on failure. Slow upstream responses or many accounts can extend that interval. The collector checks active-account status and ISP Card permissions and invalidates snapshots when credentials change.

Online users reads, searches and paginates this collected session list. Registration-client PPPoE matching uses the same complete list and requires one distinct username per MAC. Device readings are collected independently in rotating batches of up to 32, with four concurrent probes and at most 64 queued background probes. Saturated device probes do not stop session-list refreshes. Opening either page does not start these checks while the background collector is running. Tower metrics continue to use the independent inventory monitoring worker and each device's update interval.

Snapshots are held in memory for up to 64 accounts, with a maximum of 10,000 sessions per complete snapshot and a 60-second collection budget. Partial or inconsistent paginated lists are not published as complete results. Failed refreshes retain the last session list for at most five minutes and mark it stale in the interface; stale session lists are not used to assert current PPPoE username matches. Cached device readings are isolated by account, SAS4 credentials, device credentials, IP, username and session ID, and retained readings are marked as awaiting refresh.

After an API restart or a newly configured connection, the first background collection must finish. The interface shows collection progress rather than reporting zero users. An unavailable SAS4 server or unreachable device cannot supply new readings; collection retries without requiring the page to remain open. Local preview data remains a fixture and is not a live-device monitoring test.
