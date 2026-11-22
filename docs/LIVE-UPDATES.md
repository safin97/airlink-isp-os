# Live operation and quiet screen updates

AirLink collects monitoring data in background services and updates open screens in place. Normal automatic updates do not reload the browser, blank the dashboard, show a refresh spinner, or reset searches and editors. Initial loading and explicit save/connect operations can still show progress. Real connection failures remain visible so stale readings are not presented as current.

## Collection independent of a browser

- The device monitoring worker continues polling inventory using each device's configured interval.
- System performance and Deye monitoring retain their existing background collectors.
- The customer collector refreshes SAS4 online sessions and device telemetry without an open browser.
- SAS4 dashboard counts and finance values now use a separate account-scoped background snapshot service. It refreshes approximately every 30 seconds after the preceding collection finishes; failed attempts back off for 60 seconds. Dashboard and NOC-count HTTP reads reuse these snapshots rather than logging into SAS4 on every screen refresh. Cold or unavailable snapshots report unknown counts, never artificial zeroes. Last successful data is marked stale and expires after five minutes.
- Collection uses active users' saved connections, not browser login sessions. Changing a SAS4 connection invalidates its old snapshot. Permissions are checked during collection and every read. NOC-only managers receive the online count, never the finance dashboard.
- Backup schedules, notifications and payment processing retain their existing independent workers and explicit enablement settings. Live screen updates never repeat financial actions or send test messages.

## In-place updates

The main dashboard, inventory, alerts, map and permitted account data use the existing live socket, with changed-resource frames about every two seconds. If the stream stops delivering data for 15 seconds, AirLink reconnects automatically. While disconnected, the main screen reads fresh data quietly every ten seconds. Healthy sockets do not incur this fallback polling. Failed GET requests time out after 30 seconds so an abandoned read cannot hold refresh protection forever.

ISP dashboard, user lists and online users update every five seconds from the current account's permitted data. Reports update their selected page and applied filters every 15 seconds. Customer details update every ten seconds while not editing or saving; a response arriving after editing begins is ignored. Diagnostics update every ten seconds. Ethernet port views refresh every five seconds, and downtime history every 15 seconds, without showing background progress indicators. Invalid or denied live port readings are cleared rather than displayed as healthy.

Connected device panels read again every 15 seconds while not editing. Quiet reads reuse only the login that already succeeded and do not cycle through alternate credentials. Settings drafts are preserved. Login failures, changed SSH keys and states requiring a deliberate post-save reload still stop automatic reconnection; they are not bypassed to make a screen appear live.

WhatsApp account/customer status and notification history update every five seconds without overwriting unsaved account settings or re-enabling customer notifications. Deye, MEGA backup, wireless clients and update-progress panels keep their existing quiet polling/live updates.

Intervals describe refresh attempts, not guaranteed source freshness. Devices and external services may update more slowly or be temporarily unreachable. The local preview must be rebuilt and restarted to load these changes; no published software update is required for local testing.

## Server CPU efficiency

Tower inventory reads batch place membership, sector counts, device status and owner-only API settings. Device inventory reads tower API configurations in one scoped query. The number of queries no longer grows once per tower: a controlled 50-tower/200-device SQLite benchmark reduced tower reads from 201 queries to 3 and device reads from 51 to 2, with about 70% less combined CPU time for those two readers. This measures the local fixture, not total CPU usage on an installed server.

Dashboard sector counts are calculated in SQL with the same technician/manager scope as the sector list. Credentials stay server-side; no cross-account response cache is introduced. Freshness rules, session revocation checks and the two-second live stream interval remain unchanged.

Host sampling reuses its GPU detector and refreshes static PCI display names at most once a minute instead of launching `lspci` on every sample. PCI presence, loaded-driver state and available utilization readings are still read on every sample. Monitoring, SQL and networking remain CPU work; this change reduces repeated work rather than moving it to a GPU.
