# Architecture and security boundaries

Nginx terminates HTTPS and serves compiled Flutter assets. `/api/` and the authenticated WebSocket proxy to FastAPI on loopback. The API runs as the unprivileged `airlink` OS user. PostgreSQL uses Unix-socket peer authentication and an unprivileged database owner; Redis binds loopback. Monitoring and alert systemd services operate with no dashboard session.

Owner manages all inventory, accounts, monitoring, network settings and updates. Managers may alter assigned towers and their sectors/devices but cannot reassign towers or change SNMP credentials/poll thresholds. Technicians see assigned devices and may acknowledge their alerts. Viewers have read-only inventory/report access. Server queries scope related metrics, alerts and map links; the frontend is not an authorization boundary.

Access tokens expire after 15 minutes and exist only in browser memory. Refresh cookies are HttpOnly, Secure, SameSite=Strict and expire after seven days. Refresh rotates a hashed single-use token under database locks; reuse revokes its session family. The first WebSocket frame carries the access token; tokens are not put in URLs. Sessions are checked repeatedly during WebSocket delivery. Login rate limits use Redis and fail closed if it is unavailable. API request bodies and SNMP secrets are not included in the audit log.

The root controller listens on a Unix socket and checks Linux peer credentials. Its API accepts only fixed status/network/update commands, with validated network values and signed update payloads. It never accepts a caller-supplied shell command. Persistent privileged state is in root-owned `/var/lib/airlink-system`; the `airlink` user cannot replace that state. The local console requires a fresh owner login before each administrative action. First-owner creation is gated by a random local setup token and a database singleton.

SNMP profiles are Fernet-encrypted at rest using a per-install key. The API never returns ciphertext or plaintext credentials. Back up that key alongside the database; losing it prevents credential decryption. This does not provide full-disk encryption: someone with unrestricted root/disk access can read local service keys. LUKS, TPM sealing, HA clustering and multi-node worker scaling are outside this development release.

Data retention is 30 days for metrics; other records persist. Devices are polled with a bounded concurrency of eight and distributed Redis locks. Under heavy load, actual polling may lag; stale device state becomes unknown. Capacity benchmarks, load tests, hardware qualification and an external security review remain release gates.

Official implementation references:

- Debian live-boot: https://manpages.debian.org/trixie/live-boot/live-boot.7.en.html
- Debian UEFI: https://wiki.debian.org/UEFI
- NetworkManager checkpoint API: https://networkmanager.dev/docs/api/latest/gdbus-org.freedesktop.NetworkManager.html
- PySNMP API: https://docs.lextudio.com/pysnmp/v7.1/docs/api-reference


## Manager section access

Owners always have full section access. In **Managers → Section access**, the owner can select Dashboard, NOC Screen, Towers, ISP Card, Monitoring, Network Map, Alerts, Reports, Software Updates and Settings for each manager. Managers and permission administration remain owner-only. Settings and Software Updates require explicit grants; existing managers are not automatically granted either. My account/password changes remain available even if no operational section is enabled. Existing managers retain all operational sections until the owner changes their selections.

Selections are stored per user in `user_section_access`. The server checks the current stored selection on every authenticated request, including dashboard WebSocket delivery; changing access therefore does not depend on a token refresh. The sidebar refreshes the user's permissions every 30 seconds, removes denied sections, clears previously loaded page data, and switches to an allowed section. With no sections selected it shows an account-only landing message.

Shared read APIs remain available when an enabled section needs them: for example, Network Map and NOC can read the manager's scoped tower/device inventory. These reads do not enable Towers writes or Monitoring history. Alert acknowledgements require Alerts; historical metrics require Monitoring; card operations and payments require ISP Card. NOC uses a separate online-user-count endpoint that does not return ISP balance or user lists. SAS4 connection credentials are personal account settings for ISP Card/NOC users. All existing role and tower/device assignment checks still apply in addition to section access. Permission changes are audited; managers cannot change their own permissions or grant administrative access.

A Settings grant enables the Settings page's network configuration, SNMP profile creation/metadata, audit log and personal payment gateway settings. A Software Updates grant enables update checks, download/verification/install/scheduling and the update page's confirmed restart action. Existing action validation, signed update verification and preview installation restrictions still apply. Grants are checked on every request, and removing a grant immediately blocks those operations.

Manager place assignments are edited in Add/Edit Manager. Each selected place grants access to all its current and future towers and devices; moving a tower out removes inherited access. Multiple managers can share a place. Section permissions still apply. Existing direct tower assignments are preserved until an explicit place selection replaces them. Account credential edits with no place selection leave assignments unchanged. Assigned empty places remain visible. Leaving the manager role or deleting the account clears place assignments.

Section access has separate Show and Allow edits controls. A visible section without edit permission is read-only. The server checks both grants on every request, including recharge, payment setup, discovery, settings, update and restart actions. Shared connection settings require edit access to at least one section that owns them. Personal password changes remain available. Existing grants keep their prior behavior until the owner sets edit permissions; older clients cannot overwrite an explicit read-only policy. Owner access and existing role/inventory scope checks remain in force.
