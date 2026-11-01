# Development release test report

Date: 1 November 2026 (Europe/Zurich). Host: Apple ARM macOS. Guest: x86_64 QEMU 11.1.2 with OVMF UEFI and software CPU emulation, 4 GiB RAM, a 40 GiB target virtual disk, and a separate 64 MiB protected disk. No host block device was passed to QEMU.

Final ISO SHA-256:

```
1b865cd4b88ea0950b2f2e2338d6c438e3aea9060d7b32004905bf719d61272e
```

## Automated checks

- Python: **53 passed** on Debian/Python 3.13/PostgreSQL 17; **52 passed, 1 Linux-only skip** on macOS/Python 3.9.
- Alembic initial migration and four role seeds succeed. `alembic check` reports no model/schema differences.
- Tests cover bootstrap authorization, Argon2id, session rotation/reuse, logout revocation, permissions and assignment scopes, cross-tower writes, FK conflicts, credential encryption/redaction, stale status, missing metrics, input validation, CSV formula escaping, disk identity/mount/swap/mapper guards, checkpoint ordering, signed-manifest tampering/expiry/downgrade, real Debian package identity/tampering, counter resets and alert resolution.
- Flutter: analyzer reports no issues; **3 tests pass**; release web build succeeds with local renderer/font assets.
- Actual Uvicorn WebSocket connection authenticates, sends backend data and closes with code 4401 after logout revokes its session.
- A real Net-SNMP authPriv agent returns uptime, RAM and interfaces and rejects the wrong authentication key. Reference `snmpwalk` confirms this emulated host has no `hrProcessorLoad` instances. No CPU result is invented.
- Provisioning and component verification succeed in a disposable Linux container with networking disabled.

## QEMU checks

The final ISO boots through its real UEFI menu and opens the branded Qt installer. The separate automated installer-engine test uses explicit QA-only VM/disk identifiers and the same disk authorization/extraction/provisioning code as the GUI. The virtual NIC was disconnected before disk installation. Logs include:

```
AIRLINK_TARGET_COMPONENTS_VERIFIED
INSTALLATION VERIFIED — remove USB before restarting
AIRLINK_QA_PROTECTED_DISK_UNCHANGED
AIRLINK_QA_INSTALL_OK
```

The final ISO passed standalone boot without installer media: HTTPS health returned `status=ok`, setup remained uninitialized until local owner creation, and all required services appeared active on the branded console. A random-password owner was created locally, and authenticated HTTPS API plus WebSocket traffic through Nginx passed. NetworkManager automatically restored the original connection after the 120-second checkpoint expired and rejected late confirmation. The authenticated console created a uniquely named backup with relative checksums, verified both database/configuration archive checksums, and restored the database successfully. API health and required services passed afterward; a fresh owner login and authenticated WebSocket connection also passed after restoration. This rehearsal used a small test database, not a production inventory or encryption-key disaster recovery scenario.

Live-media shutdown prompts to remove the medium and press Enter. This is distinct from the already completed, synchronized target installation. The automated harness ends the VM at that prompt and boots the installed disk separately.

## Limits

This is not a physical hardware certification, a security audit, or a load/endurance test. The graphical wizard was rendered/booted; destructive engine execution was automated using QA identifiers, not a recorded click-through of every wizard page. The backup/restore rehearsal used a small test database. Signed update verification does not establish that an upgrade/rollback migration pair is safe. No vendor wireless/client adapter or full atomic OS update path is claimed.

Raw logs and screenshots are retained in `test-results/`; virtual disks are excluded from the source archive. Read PROGRESS.md before production use.
