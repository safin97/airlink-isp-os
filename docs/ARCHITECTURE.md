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
