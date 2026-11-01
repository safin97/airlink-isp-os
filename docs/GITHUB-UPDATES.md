# Updates through GitHub Releases

AirLink can fetch signed application updates from a **public GitHub repository**. Its existing updater accepts a signed `stable.json` release asset and the exact `.deb` package referenced by that manifest. GitHub hosts the files; the installed Ed25519 public key determines which publisher is trusted. No GitHub token or signing private key belongs on the appliance.

The configured repository is `safin97/airlink-isp-os`. The source tree includes its update URL and public publisher key in `deployment/update-source/`; provisioning seeds these on a new installation and preserves existing site configuration. A transfer bundle is in `dist/github-config/`. Source code was uploaded successfully to the repository on 1 November 2026. Earlier repository-access failures are resolved. The first signed development release is `v0.1.0-dev`; its assets include `stable.json` and the signed package. It is published on the repository Releases page. The actual updater passed anonymous Check → Download → Verify against the public assets.

Publisher public-key SHA-256: `b4ae47eb2992e80384df54d23e0b7300bc85aac7813ae21ca44b5fc2a31fda9e`.

The original ISO in `dist/` remains unchanged. The updated image is `dist/github-enabled/AirLink-ISP-OS-amd64.iso`. Neither image contains the private key. The original updater accepts the generated configuration without a code upgrade.

## 1. Establish the publisher key

On a trusted signing workstation, from the source directory:

```sh
.venv/bin/python os/updates/github_release.py init-key \
  --directory .release-secrets
```

A key has already been generated locally in `.release-secrets/` for this repository; retain it for every subsequent release. Do not rerun initialization to rotate keys. For a separate new publisher, this command creates a private PEM with mode 0600 and a raw 32-byte public key. It refuses to replace existing keys. Keep the private key offline and backed up securely; never upload it to GitHub or copy it to the appliance. `.release-secrets/` is excluded from Git and Docker build context. Losing it prevents signing future releases for appliances that trust this key.

## 2. Configure the installed appliance

Replace `safin97/airlink-isp-os` with your actual public repository:

```sh
.venv/bin/python os/updates/github_release.py configure \
  --repo https://github.com/safin97/airlink-isp-os \
  --public-key .release-secrets/update-public-key.bin \
  --output dist/github-config
```

The output contains only `update-source.json` and `update-public-key.bin`. Compare the printed SHA-256 fingerprint against the publisher's trusted copy. Transfer these two files to the installed appliance using trusted removable media. From a local administrative recovery shell, install them as root:

```sh
install -o root -g root -m 0644 /PATH/TO/github-config/update-public-key.bin /etc/airlink/update-public-key.bin
install -o root -g root -m 0644 /PATH/TO/github-config/update-source.json /etc/airlink/update-source.json
```

These commands establish initial trust. Do not replace an existing publisher key during an update or as a casual key-rotation procedure. The application reads the files on the next update request; no service restart is necessary. Configuration in a live session is temporary; use the installed OS for persistent setup.

The source URL follows GitHub's documented latest-asset route:

`https://github.com/safin97/airlink-isp-os/releases/latest/download/stable.json`

Only a published release with this asset will work. Drafts, a repository without releases, and private repositories requiring authentication are not supported by this download route. Keep this repository's latest release reserved for AirLink updates. The generic `dist/release-manifest.json` describing the ISO is **not** the updater's signed `stable.json`.

## 3. Build and sign an update

Build the Flutter bundle and amd64 runtime image from the reviewed source as described in README.md. Then package that image, using a real new Debian version:

```sh
mkdir -p dist/packages
docker run --rm --platform linux/amd64 \
  -v "$PWD/dist/packages:/output" airlink-isp-os:0.1.0-dev \
  bash /opt/airlink/os/updates/build-package.sh 0.2.0 /output
```

Use an image built from the intended new source; changing the package version alone does not build new code or update the application's version setting. Validate the package identity and rehearse installation/database recovery in a spare VM before signing it. This is an application package, not a complete kernel/base-OS upgrade.

Write release notes in `release-notes.md`, then prepare the public assets on the signing workstation:

```sh
.venv/bin/python os/updates/github_release.py prepare \
  --repo safin97/airlink-isp-os \
  --key .release-secrets/publisher-private.pem \
  --package dist/packages/airlink-isp-os_0.2.0_amd64.deb \
  --version 0.2.0 --sequence 1 \
  --expires 2027-01-01T00:00:00Z \
  --notes release-notes.md \
  --output dist/github-release-0.2.0
```

Choose an appropriate future expiry, and increase the sequence for every release. The helper validates the signed manifest and stages the package, `stable.json`, notes, and checksums in a new directory. It does not execute or certify the package; the appliance also checks the Debian name, architecture and version. Never reuse a version/tag with different content. All appliances must have a sufficiently accurate clock to validate expiry and HTTPS.

## 4. Publish the reviewed release

Authenticate GitHub CLI on the publisher workstation, push the reviewed source and tag `v0.2.0` to the intended repository, then publish the prepared assets:

```sh
gh release create v0.2.0 \
  dist/github-release-0.2.0/airlink-isp-os_0.2.0_amd64.deb \
  dist/github-release-0.2.0/stable.json \
  dist/github-release-0.2.0/SHA256SUMS \
  --repo safin97/airlink-isp-os --verify-tag --latest \
  --title 'AirLink ISP OS 0.2.0' \
  --notes-file dist/github-release-0.2.0/release-notes.md
```

The assets must be public. Never attach `.release-secrets/`, private keys, backups, or appliance configuration containing credentials. Source commits alone do not produce an update. The owner uses **Software Updates → Check → Download → Verify → Install**, or schedules an installation. Updating remains owner-controlled; merely linking GitHub never triggers installation.

## Verification and limits

The GitHub helpers have 18 automated tests covering accepted/rejected repository URLs, non-replacement and permissions of signing keys, idempotent initial provisioning, preservation of existing trust, public-only configuration, manifest compatibility with the deployed verifier, replay rejection and signature tampering. The existing ISO's signed-update engine is unchanged. The first signed package passed an isolated QEMU installation rehearsal with preserved test data and encrypted credentials; see [release verification](releases/0.1.0-dev-verification.md). Future package/schema combinations still require their own rehearsal. Rollback remains disabled.

References: [GitHub release download links](https://docs.github.com/en/repositories/releasing-projects-on-github/linking-to-releases) and [GitHub CLI release creation](https://cli.github.com/manual/gh_release_create).
