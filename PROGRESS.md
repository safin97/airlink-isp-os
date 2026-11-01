# AirLink ISP OS — delivery status

Version **0.1.0-dev**, built 1 November 2026. This is a working development appliance, not completion of every production requirement in the master prompt. No existing starter files were present in the workspace.

| Phase | Implemented and verified | Remaining work |
|---|---|---|
| 1 — Image | Debian 13 amd64 kernel/firmware, pinned container base, dependency locks, native Linux filesystem staging, SquashFS/GRUB ISO. Final ISO UEFI menu and graphical live boot verified in QEMU. | Immutable Debian repository snapshots and bit-for-bit rebuild equivalence; physical hardware qualification. |
| 2 — Installer | Local Qt wizard; exact disk identity/model/size review; acknowledgment plus `ERASE`; mounted media/swap/mappers protected; offline extraction and target-only EFI installation. Final ISO installed successfully on a fresh 40 GiB QEMU disk with network link disconnected. Entire second 64 MiB disk unchanged. | Only English is implemented. Full GUI interaction automation and more storage-controller combinations. |
| 3 — Provision | PostgreSQL, Redis, Python app, workers, Flutter assets, Nginx, nftables and systemd installed offline. Target verification gates success. Networking-disabled container provisioning passed; QEMU target checks passed. | Additional firmware/hardware coverage and unattended failure/power-loss matrix. |
| 4 — First boot | DHCP and validated static IPv4; local owner wizard; Argon2id; singleton initialization; random setup token; NetworkManager checkpoints. Owner setup and 120-second rollback verified in QEMU. | Static addressing and DNS on physical networks; reboot-during-network-change qualification. |
| 5 — Dashboard | Responsive Flutter app, real API inventory/metrics, charts, map, errors/empty states, settings and reports. Analyzer clean; 3 Flutter tests passed; release bundle built; desktop Chrome sign-in/render verified. | Device/browser testing on iPhone and Android; accessibility and larger inventory usability review. |
| 6 — Management | Tower/sector/device CRUD, owner/manager/technician/viewer roles, manager tower assignments, technician device assignments, alert acknowledgment and audit records. PostgreSQL RBAC tests pass. | Rich account editing/password recovery, bulk workflows, pagination and capacity improvements. |
| 7 — Monitoring | SNMPv3 SHA-256/AES-128, ICMP, IF-MIB/HOST-RESOURCES-MIB, history, counter reset handling, thresholds, alert lifecycle, geographic tower map and owner-verified links. Real SNMPv3 lab uptime/RAM/interfaces and wrong-key rejection pass. | Vendor MIB adapters for wireless signal/frequency/client counts, client enumeration and actual MikroTik/Ubiquiti/Mimosa hardware testing. The lab exposes no CPU-load instances; CPU collection remains unqualified on hardware. |
| 8 — Remote access | HTTPS Nginx, local-only database/cache/API, firewall, memory-only access tokens, HttpOnly refresh cookies, rotation/reuse revocation, Redis rate limiting and authenticated WebSockets. Real Uvicorn WebSocket auth/revocation tested. | Site-specific trusted domain certificates/VPN configuration; external security review. |
| 9 — Updates/recovery | Ed25519 manifest verification, package digest/size/identity checks, expiry/replay defense, owner-only update actions, persistent scheduling, backup, migration/health gates and interrupted-update state. Signature and real Debian package tamper tests pass. Basic QEMU database backup/restore rehearsal passed. | The original ISO needs the published GitHub configuration bundle; the GitHub-configured ISO includes publisher trust. A first signed package installation with preserved test data and encrypted credentials passes in QEMU. Interrupted upgrades, larger populated-data restoration, key recovery and rollback still need qualification. Full atomic base-OS/kernel updates are not implemented. Rollback stays disabled. |
| 10 — Release QA | 53 Python tests pass on Linux/PostgreSQL; 52 pass on macOS with one Linux-only skip. Final ISO passes offline install, protected-disk check, UEFI/live boot, standalone boot, console owner setup, HTTPS API/WebSockets, timed network rollback and basic database backup/restore in QEMU. | Endurance/load/security testing and production acceptance remain open. |

## Release boundaries

- Unsupported metrics are `null`/unavailable, not fabricated. New/stale devices are `unknown`.
- The 24-hour availability percentage covers observed ICMP samples, not unsampled time.
- Secure Boot is unsupported by this custom development image; disable it for VM/hardware testing.
- Database and Redis are not exposed publicly. The installed PostgreSQL listener uses its local Unix socket.
- The API and monitoring are real implementations; the isolated browser QA fixture uses an ephemeral test database/cache and is not the appliance deployment.
- No publisher private key, default owner password, or configured public update endpoint is shipped.

Evidence is in `test-results/` and [docs/TEST-REPORT.md](docs/TEST-REPORT.md). Installation, updates and recovery procedures are in `docs/`.

## GitHub update integration — source follow-up

Added publisher tools for repository URL validation, offline Ed25519 key creation, appliance source configuration and signed GitHub Release assets. Eighteen dedicated tests pass. These tools use the original ISO's manifest format; the original tested ISO is unchanged. A separate GitHub-configured ISO was built in `dist/github-enabled/`. The full Python suite now reports 70 passes and one Linux-only skip on macOS. Offline provisioning and component verification pass with the correct root-owned public key/source installed; no private key is included. The separate ISO also passed QEMU UEFI/live graphical boot and HTTPS health. The repository URL and public signing key are configured in `deployment/update-source/` for `safin97/airlink-isp-os`, with an existing-install transfer bundle in `dist/github-config/`. Repository access is now working, and the source was uploaded to `main` on 1 November 2026. The first signed development release uses package version `0.1.0-dev` and sequence 1; its installation rehearsal is documented in `docs/releases/0.1.0-dev-verification.md`. Live GitHub downloads and a full signed upgrade remain unqualified. See [docs/GITHUB-UPDATES.md](docs/GITHUB-UPDATES.md).

## Published development release

[v0.1.0-dev](https://github.com/safin97/airlink-isp-os/releases/tag/v0.1.0-dev) was published on 1 November 2026 with 13 verified assets, including the bootable ISO, signed application package, manifest and source archive. Anonymous GitHub Check/Download/Verify passed using the real updater. The exact package also passed a QEMU install rehearsal preserving a test tower, owner access and encrypted SNMP credentials. This qualifies the initial package path, not arbitrary future migrations, hardware, interrupted updates or rollback. The release remains a development build.
