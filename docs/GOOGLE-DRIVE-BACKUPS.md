# Google Drive backups

Owners can open **Settings → Google Drive backup** to connect their Google account, choose a weekly day/time/timezone, and run **Back up now**. Managers cannot read or change these settings, even when granted Settings access.

The installed appliance creates a PostgreSQL custom-format dump plus the existing configuration archive (AirLink secrets, network profiles and nginx configuration). It verifies local SHA-256 checksums, bundles these files and encrypts the bundle before uploading. Each encrypted file is uploaded into an AirLink folder in the connected account. The completed upload's size and MD5 are checked against the encrypted local file; AirLink also records its SHA-256. Upload completion means the stored bytes were verified, not that a full disaster-recovery rehearsal has been performed.

## One-time connection

1. Give the AirLink dashboard an HTTPS domain and a valid certificate, and open that domain in your browser. A public IP such as `https://185.206.82.100` cannot be a Google web OAuth callback. Localhost HTTP is allowed for development only. Google requires the callback to match the registered URL exactly. See [Google's web OAuth rules](https://developers.google.com/identity/protocols/oauth2/web-server#uri-validation).
2. In your Google Cloud project, enable **Google Drive API**, configure the OAuth consent screen, and create an OAuth client of type **Web application**. Use an appropriate production or Workspace-internal configuration for ongoing backups. External apps left in **Testing** receive refresh tokens that expire after seven days, so they are unsuitable for a recurring weekly schedule. See [Google's refresh-token expiration rules](https://developers.google.com/identity/protocols/oauth2#expiration).
3. Register `https://YOUR-AIRLINK-DOMAIN/api/backups/google-drive/callback` as an authorized redirect URI. Copy the client ID and secret into AirLink's owner-only backup settings. These are OAuth app credentials, not your Google account password.
4. Enter a separate backup encryption password of at least 12 characters and confirm it. **Keep this password outside the appliance**, for example in your password manager. It is required to decrypt a downloaded backup; neither AirLink nor Google can recover a lost password. Changing it affects future backups only; keep the old password for older files.
5. Enable **Weekly automatic backup** and choose a day, time and IANA timezone, such as `Asia/Baghdad` or `Europe/Zurich`. The initial selection is Sunday at 02:00 UTC. Save settings, then click **Connect Google Drive**. Allow pop-ups for AirLink and approve access in Google's window.
6. Run **Back up now**, wait for **completed**, and check **Open backup folder**. Rehearse recovery on a spare system before relying on cloud backups.

Only `https://www.googleapis.com/auth/drive.file` is requested: the application works with files it creates, rather than requesting access to all existing Drive files. See [Google's Drive scope documentation](https://developers.google.com/workspace/drive/api/guides/api-specific-auth).

## Scheduling and status

The root-owned `airlink-controller` service checks the schedule once per minute. It runs while users are logged out and no webpage is open. The server must be powered on with internet access and sufficient local disk space. If the scheduled time passes while the server is off, one catch-up backup starts after the controller resumes; the next run is scheduled for the next weekly slot. A failed scheduled run appears in status/history; use **Back up now** after correcting the problem, or wait for the next weekly run. It does not retry indefinitely.

The selected timezone determines the weekly time, including seasonal UTC offset changes. During a spring clock change, a nonexistent local time runs at its corresponding later valid time. A fall repeated local time produces one backup. The status timestamps are displayed in the viewing browser's local timezone.

Only one cloud backup runs at a time. Updates, console maintenance and database recovery use the same maintenance lock. A backup blocked by a running/pending update fails with an explanatory message; retry after maintenance. The page shows progress, next scheduled run, last successful backup and the latest 20 job results. Closing the page does not cancel an upload.

Local recovery copies remain under `/var/backups/airlink`. Cloud backups remain in Google Drive until you delete them yourself; there is no automatic deletion or retention limit. Monitor both local disk and Google storage. Disconnecting stops the weekly schedule, removes the local OAuth refresh token and attempts to revoke Google authorization. It keeps existing backups. You can also revoke AirLink access in your Google Account.

If Google denies access, tokens expire, or the account is disconnected, reconnect from the owner page. Changing the OAuth client or callback requires reconnecting. Changing the folder name creates a new folder on the next upload; earlier folders/files are retained.

The local development preview can display settings but cannot create appliance backups or run its scheduler. No backup is simulated as successful.

## Recovery

Download a completed `.tar.airlink` file from Drive to a trusted Linux machine or spare AirLink appliance. Keep the original encrypted file. The standalone decryption tool requires Python 3 and `cryptography` (already installed on AirLink; Debian package `python3-cryptography`).

```sh
python3 /opt/airlink/os/recovery/cloud_archive.py AirLink-DOWNLOADED.tar.airlink recovered.tar
```

The tool asks privately for the encryption password. It authenticates the entire file before publishing the output, refuses to overwrite an existing output and removes temporary plaintext if authentication fails. `recovered.tar` contains only `database.dump`, `configuration.tar.gz` and `SHA256SUMS`. Decrypted files contain sensitive data and must stay in protected storage.

Inspect the archive, extract its three expected regular files into a new protected recovery directory, and verify `sha256sum -c SHA256SUMS`. Follow [local recovery instructions](RECOVERY.md) to place the verified backup under `/var/backups/airlink` and restore from the authenticated console. Review configuration separately: the matching AirLink encryption key may be required to decrypt stored device credentials, and restoring old network configuration may disconnect the machine. Restore to a compatible application/database version and validate the database, API and credential decryption on a spare VM first.

The backup is application data/configuration, not a disk image or operating-system installer. Google OAuth credentials, tokens and the backup password are stored separately under the root-only `/var/lib/airlink-system/google-drive-backup` directory, encrypted using a root-only local key; they are not included in the cloud archive or returned by the API. After reinstalling the appliance, reconnect Google Drive and re-enter the externally retained backup password. The archive encryption uses a versioned header, a random salt and nonce, scrypt password derivation and streaming AES-256-GCM authentication.

## Validation limits

Automated tests cover scheduling without a browser, owner access restrictions, secret redaction, OAuth state/owner/expiry checks, encryption and authenticated recovery, chunk upload resumption/checksums, and configuration upgrade rules. Google responses are simulated in those tests. Live Google consent and upload require your own configured OAuth client and HTTPS domain and must be checked during setup.

Local validation on 10 November 2026: 602 backend tests passed (one Linux package test skipped on macOS), 106 Flutter tests passed, Flutter analysis and the production web build passed. `tests/google_drive_linux_qa.py` also passed in a disposable offline Debian container using the appliance's system Python: actual PostgreSQL dump, encrypted archive recovery, configuration/checksum verification, restoration into a separate fixture database, and a request to the real root controller's Unix socket. This fixture rehearsal does not replace recovery testing with your own database and credentials.
