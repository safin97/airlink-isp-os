# Recovery

Owners can also [create and download an encrypted backup](DOWNLOAD-BACKUPS.md) from **Settings → Backups**, without a cloud account or a domain.

For automatic weekly off-site copies without a domain, configure [MEGA cloud backups](MEGA-BACKUPS.md) on the same page.

Use the local console after owner authentication for service restarts, logs and database backup/restore. Backups are in `/var/backups/airlink/<UTC timestamp>-<unique suffix>` with SHA-256 checksums. Copy them to separate protected storage; they contain database records and encryption keys.

On versions with **PC settings → System → Open Terminal**, sign in as owner on the AirLink PC's own screen and confirm root access. The terminal runs commands as root, so `sudo` is unnecessary. Type `exit` when finished; the panel returns to sign-in. The terminal closes after 15 minutes and holds the maintenance lock while open, so close it before retrying an update. A failed-update marker does not prevent terminal access, but an active installer does. If owner login is unavailable, use installer-media Recovery Mode.

For an interrupted update, inspect `journalctl -u airlink-update-job` and `/var/lib/airlink-system/updates/state.json`. Do not clear an `installing` or `failed` marker until the installed package and database migration state have been reviewed. Automatic rollback is deliberately disabled: no application/database rollback combination has been certified yet.

Database restore: run `/opt/airlink/os/recovery/restore.sh /var/backups/airlink/TIMESTAMP RESTORE` from the authenticated console workflow. It stops writers, takes a fresh backup, verifies checksums, and restores the database transactionally. It runs schema migrations before restarting services and restores the safety database if migration fails. Saved sessions are cleared after successful recovery. Review configuration archives separately; restoring old network files can disconnect the server. Restore the matching encryption key from the configuration backup if SNMP secrets were encrypted under a different key. Owners can also select and verify a MEGA backup through **Settings → Backups → Restore from MEGA**; see [MEGA backups](MEGA-BACKUPS.md) for platform and encryption-key requirements.

If the installed system cannot boot, boot the AirLink USB in Recovery Mode. This grants local recovery tools to the person with physical control of the boot media. Inspect `lsblk -f` before mounting any filesystem. Mount the installed root read-only first; preserve logs and backups before making changes. No disk is automatically erased in recovery. The development ISO is not a defense against an attacker who can boot alternate media.

A valid recovery rehearsal must include a restore on a spare VM, database validation, API startup and SNMP credential decryption. Consult PROGRESS.md for the tests actually performed on this release.

For encrypted off-site copies and password-based decryption, see [MEGA backups](MEGA-BACKUPS.md).
