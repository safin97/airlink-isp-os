# Signed software updates

For a public GitHub repository, use the configuration and signed release tools in [GITHUB-UPDATES.md](GITHUB-UPDATES.md). They work with the current ISO's update format. Linking a repository does not automatically install releases.

The source configuration now selects the public GitHub repository `safin97/airlink-isp-os` and its publisher public key for new installations. The original ISO remains unconfigured until the generated configuration bundle is installed. Private signing keys are never included in an image. Without a trusted public key and source, the update UI is disabled. Only owners can check/download/verify/install/schedule updates.

Store a raw 32-byte Ed25519 publisher public key at `/etc/airlink/update-public-key.bin` and a root-owned JSON configuration at `/etc/airlink/update-source.json`:

```json
{"manifest_url":"https://YOUR-TRUSTED-DOMAIN/releases/stable.json"}
```

The envelope has `manifest` and a base64 `signature`. The signature covers the UTF-8 JSON manifest serialized with sorted keys, separators `,` and `:`, and no extra whitespace. Required manifest fields are `version`, increasing integer `sequence`, package `sha256`, exact `size`, HTTPS `url`, timezone-qualified `expires`, `release_notes`, and boolean `reboot_required`. Both manifest signature and package digest/size are verified before installation. Only an amd64 Debian package named `airlink-isp-os` with exactly the signed version is accepted. HTTPS redirects may not downgrade to HTTP. Old sequences and expired manifests are rejected.

Keep private keys offline. A compromised trusted publisher can supply privileged Debian package scripts, so protect publisher signing and release review. Untrusted remote scripts are never downloaded/executed as an update mechanism.

The service checks health and free space, stops writers, takes a PostgreSQL/configuration backup, installs the verified package, runs Alembic migrations, restarts workers/API, and verifies health. The journal and root-owned state file distinguish accepted actions from completed installation. A failed/interrupted update requires local review. Database migrations must use backward-compatible expand/contract design and pass a restore rehearsal before signing a release. A unit-tested verifier is not proof of a safe upgrade.

Scheduling writes a persistent systemd calendar timer with an explicit UTC date. Publisher key rotation still requires a reviewed local procedure. Rollback is disabled until a specific package/database rollback pair has been tested. Recovery instructions are in RECOVERY.md. Do not enable the Rollback button based only on the existence of a backup.

Publisher utilities are `os/updates/build-package.sh` (run inside the amd64 application image) and `os/updates/sign_manifest.py` (run on the signing workstation). The current package contains the application/venv and fixed systemd files. It does **not** implement a full atomic kernel/base-OS upgrade. A separately qualified Debian security-update procedure or signed full-image upgrade mechanism is still needed before production operation.
