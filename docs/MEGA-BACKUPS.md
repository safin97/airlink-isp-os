# MEGA cloud backups

Owners can open **Settings → Backups → MEGA cloud backup**. A public IP or localhost is sufficient; MEGA backups do not use Google OAuth, callback URLs or a domain.

## Setup

1. Sign in to your MEGA account on its website at least once so its encryption keys are initialized.
2. Expand **MEGA account and weekly schedule**. Enter your MEGA email/password, a destination folder, and a separate backup encryption password of at least 12 characters. Keep the encryption password outside AirLink; it is needed for recovery.
3. Leave **Weekly automatic MEGA backup** enabled and choose a day, time and IANA timezone. The initial selection is Sunday at 02:00 in Europe/Zurich. You can change it before saving.
4. Select **Save MEGA settings**, then **Test MEGA connection**. The connection test authenticates and creates the destination folder if necessary. Saving settings alone does not establish a verified connection or upload a backup.
5. Select **Back up to MEGA now** for the first backup. Check for **completed** and the last verified filename. Thereafter the live server runs the weekly schedule without an open browser or signed-in owner.

This integration uses rclone's MEGA backend with unattended email/password authentication. It does not store or regenerate one-time sign-in codes and therefore does not support accounts requiring a fresh code for each login. Changing account credentials or the destination folder requires another successful connection test. Passwords never appear in API responses or command arguments. Account and backup passwords are encrypted at rest in the controller's private settings directory.

## Local Mac and installed appliance

The installed image includes the transfer binary; application packages built from that image include it too. The installed controller starts the scheduler at boot. Backups contain the same PostgreSQL database/configuration archive used by the other appliance backup options.

For the local checkout, install the transfer helper once:

```sh
python3 scripts/install-backup-transfer.py
./scripts/live.sh
```

The installer downloads a pinned rclone release from the official host, verifies its published SHA-256 and installs it under the ignored `.tools/` directory. You can instead use a system `rclone` or set `AIRLINK_RCLONE_BIN` to its absolute path. Local credentials/settings are in the ignored, private `.local/mega-backups/` directory. Keep this directory private and preserve it if moving the local installation.

Local mode uploads the local SQLite database and recovery key, not a PostgreSQL appliance backup. Keep the Mac awake, online and the live launcher running. Demo mode does not run MEGA uploads or its scheduler. If the server was off at the scheduled time, the next live start catches up once and schedules the next future weekly occurrence. A manual backup does not postpone the weekly deadline. Failed attempts are shown in history; use **Back up to MEGA now** to retry. An interrupted backup is marked failed after restart.

## Verification, retention and recovery

AirLink creates a consistent archive, encrypts it with the existing scrypt/AES-256-GCM backup format, uploads a uniquely named `.tar.airlink` file, then reads the remote encrypted bytes back for comparison. A job is only marked completed after verification succeeds. This consumes upload and download transfer quota. Storage/quota, network or authentication failures never count as a completed backup.

Only the encrypted file is uploaded. Existing MEGA files are not deleted or synchronized away. Disconnecting removes AirLink's stored MEGA account password and disables the schedule; it keeps remote backups and the saved backup encryption password. Monitor MEGA storage and quota and remove old backups through your MEGA account when appropriate.

### Restore from the dashboard

1. Sign in as owner and select **Settings → Backups → MEGA cloud backup → Restore from MEGA**.
2. Select a backup from the configured MEGA folder (up to 500 newest AirLink files), enter the encryption password used for that backup, and select **Download and verify backup**. The MEGA account password is different from this encryption password.
3. Wait for **ready**. AirLink authenticates/decrypts the file, checks checksums and safe archive contents, and checks platform compatibility. Incorrect passwords, damaged files and incompatible backups cannot reach confirmation. Online recovery supports files up to 20 GiB and requires free space for temporary files and a safety backup.
4. Review the selected filename, type **RESTORE**, and select **Confirm restore**. This replaces current database records; later changes will be lost. A verified selection expires after one hour and can be cancelled before confirmation. Only the owner who prepared it can confirm it.
5. **Local Mac:** recovery waits for restart. Stop the local server, then run `./scripts/live.sh` again. Before opening application connections, the launcher saves the current database and key to a private `.local/mega-backups/before-restore-*` directory, restores the selected SQLite database/key and clears saved sessions. The launcher holds an exclusive process lock to prevent concurrent local servers. Your next backups use the restored key. A saved recovery key in `.local/mega-backups/local-recovery-key` takes precedence over the environment default.
6. **Installed appliance:** services stop briefly, a safety backup is created under `/var/backups/airlink`, and the database is restored transactionally. Schema migrations run before services restart; a migration failure restores the safety database. Existing network settings and service secrets are kept. If the archive uses a different encryption key, web recovery is rejected: use the local console recovery procedure and review the matching configuration instead. Private recovery logs are in `/var/backups/airlink/mega-*/recovery.log`.
7. Sign in again with an active owner account and password from the backup. Review the restored data. The MEGA account and schedule stay configured, and scheduled backups resume after recovery.

Local SQLite backups and appliance PostgreSQL backups are not interchangeable. Local recovery rejects missing columns in existing tables; use a compatible AirLink version to recover older schemas. You can also download a backup using MEGA's own website or app and follow [download backup recovery](DOWNLOAD-BACKUPS.md), or [Recovery](RECOVERY.md) on an appliance. These files are application backups, not complete disk images. MEGA credentials/schedule settings are not included in the archive and must be reconfigured after a fresh installation.

Implementation references: [rclone MEGA backend](https://rclone.org/mega/), [rclone copyto](https://rclone.org/commands/rclone_copyto/), [file listing](https://rclone.org/commands/rclone_lsjson/), [download verification](https://rclone.org/commands/rclone_check/), and [password input via stdin](https://rclone.org/commands/rclone_obscure/). rclone password obscuring is reversible; AirLink uses its own encrypted settings storage and a short-lived private rclone configuration file.

Automated tests exercise scheduling/catch-up/restarts, owner permissions, secret redaction, encrypted archive recovery and transfer failure handling. A successful live MEGA login/upload requires the owner's account and is not implied by the automated tests.
