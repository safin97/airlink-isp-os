# Download and restore a backup

Sign in as owner and open **Settings → Backups → Download a backup**. Enter and confirm a password of at least 12 characters, select **Create backup**, then **Download backup** when it is ready. No Google account, OAuth client, domain or internet connection is required. Access through the server's public IP works with this feature. Keep the page open until the file is downloaded; files are available for one hour and pending downloads are invalidated by a server/controller restart.

Keep the `.tar.airlink` file and its password in separate safe places. AirLink does not save this password. Temporary encrypted downloads are removed when expired during subsequent backup requests. The installed appliance also retains its existing local recovery copy under `/var/backups/airlink`.

## Contents

- Installed appliance: PostgreSQL `database.dump`, `configuration.tar.gz` (AirLink secrets, network profiles and nginx configuration), and `SHA256SUMS`. Uses the same checked archive and maintenance lock as MEGA backups.
- Local Mac preview: a consistent SQLite `database.sqlite`, `recovery.json` containing the credential encryption key and format identifier, `README.txt`, and `SHA256SUMS`. This is a local development backup, not an appliance PostgreSQL backup.

Both formats use the existing password-encrypted AirLink archive format. Only the owner who created a job can inspect or download it. Failed jobs never publish a downloadable archive. Downloading uses browser memory, so very large archives require enough free browser memory.

## Recover

### Browse a backup file from your PC

1. Sign in as owner and open **Settings → Backups → Download a backup → Restore from PC file**.
2. Select **Browse backup file** and choose the encrypted `.tar.airlink` file saved on your computer. Files saved by AirLink's download or cloud backup options use the same encryption format. No cloud connection is required.
3. Enter the encryption password used when that backup was created and select **Upload and verify backup**. Keep the dialog open during upload. The browser reads and uploads small chunks rather than loading the entire file into memory. Online recovery supports files up to 20 GiB, subject to free server space.
4. Wait for **ready**. AirLink checks the password, authenticated encryption, archive structure, checksums and database compatibility. Uploading or verifying does not replace current data.
5. Review the filename, type **RESTORE**, and select **Confirm restore**. The server saves a safety backup before replacement. Changes made after the selected backup will be lost. Only the owner who prepared the recovery can confirm it.
6. On your local Mac, stop the local server and run `./scripts/live.sh` again to apply the confirmed restore. On the installed appliance, services restart automatically after recovery. Sign in with an account and password from the restored backup.

Interrupted uploads can be cancelled from the restore dialog and uploaded again. Incomplete uploads and unconfirmed verified files expire after one hour; a controller restart also discards them. The upload password is not saved. Only one file or MEGA recovery can run at a time.

SQLite backups restore to the local app and PostgreSQL backups restore to the appliance. The appliance web workflow keeps existing network configuration and requires the backup's credential encryption key to match the current installation; use console recovery for a different key. See [MEGA recovery](MEGA-BACKUPS.md) for the shared safety-copy, schema and restart behavior.

### Offline recovery

Backups stored in MEGA can be selected and restored through **Settings → Backups → Restore from MEGA**; see [MEGA recovery](MEGA-BACKUPS.md). That workflow verifies the archive before confirmation and saves a safety copy before replacing data.

Decrypt on a trusted machine with Python and `cryptography` installed:

```sh
python3 os/recovery/cloud_archive.py AirLink-DOWNLOADED.tar.airlink recovered.tar
```

On the appliance the script is `/opt/airlink/os/recovery/cloud_archive.py`. It prompts for the password and verifies the encrypted file before publishing the decrypted archive. Inspect and extract into a new private directory, then verify `SHA256SUMS` (`sha256sum -c SHA256SUMS` on Linux, `shasum -a 256 -c SHA256SUMS` on macOS).

For an appliance backup, follow [Recovery](RECOVERY.md). For a local SQLite backup, stop the launcher, preserve the current database, restore `database.sqlite` to `/tmp/airlink-browser-qa.sqlite`, and provide the matching `AIRLINK_ENCRYPTION_KEY` from `recovery.json` when restarting `scripts/live.sh`. If a prior dashboard restore saved `.local/mega-backups/local-recovery-key`, that file takes precedence; preserve it with the safety copy and update it to the matching recovery key. Reuse a compatible application version. Do not overwrite a running SQLite database or restore it using the appliance PostgreSQL restore script.

Extracted files contain secrets. This backup contains application data and configuration, not an operating-system image. MEGA connection settings are stored separately and must be reconfigured after appliance recovery.
