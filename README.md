<p align="center"><img src="os/branding/airlink-header.svg" alt="AirLink — Telecommunication company" width="420"></p>

# AirLink ISP OS

A Debian 13 based x86_64 monitoring appliance with a local Qt installer, FastAPI/PostgreSQL backend, independent monitoring and alert workers, and a Flutter web dashboard.

**Development release, not a certified production appliance.** See [PROGRESS.md](PROGRESS.md) for verified behavior and remaining requirements. Never use the erase installer on a disk containing data you need. No default owner password exists.

Download development releases from [GitHub Releases](https://github.com/safin97/airlink-isp-os/releases). Signed application updates are installed through the owner-only Update Center.

## Build

Prerequisites: Docker with Linux amd64 support, Flutter 3.47 or compatible Dart >=3.8, QEMU with OVMF, at least 40 GB free build space (80 GB recommended), and internet access while building. Installation from the resulting image is offline; monitoring does not require internet. Online map tiles and software downloads do.

```sh
cd frontend
flutter pub get
flutter analyze
flutter test
flutter build web --release --no-web-resources-cdn
cd ..
bash os/build/build.sh
```

The image output is `dist/AirLink-ISP-OS-amd64.iso` with `dist/SHA256SUMS` and a Debian package inventory. The base image digest and Python/Flutter dependency locks are checked in. The recipe is repeatable, but exact Debian repository snapshots and bit-for-bit ISO equivalence are not yet validated. Retain the package inventory and source archive for every release. Do not describe the recipe as a bit-reproducible build.

## Test

```sh
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements.lock pytest fakeredis
.venv/bin/pytest -q
```

The Python suite uses disposable SQLite by default; `tests/linux-integration.sh` runs the suite against PostgreSQL inside a disposable Linux container. The suite ignores an inherited application `DATABASE_URL`; only `AIRLINK_TEST_DATABASE_URL` explicitly opts into another disposable test database. Never point that variable at a production database: fixtures drop and recreate application tables.

See [installation](docs/INSTALLATION.md), [local PC settings](docs/LOCAL-PANEL.md), [architecture and security](docs/ARCHITECTURE.md), [updates](docs/UPDATES.md), [recovery](docs/RECOVERY.md), and [monitoring support](docs/MONITORING.md).

To host signed application updates on your own public GitHub repository, see [GitHub Releases setup](docs/GITHUB-UPDATES.md).

## Repository

- `os/`: guarded installer, branding/boot configuration, NetworkManager checkpoints, local console, update verifier and image build.
- `frontend/`: Flutter dashboard, inventory forms, map, charts and administration.
- `backend/airlink/`: authenticated API, explicit RBAC, database models and encryption.
- `monitoring/`: autonomous SNMPv3/ICMP collection and alert evaluation.
- `database/`: versioned Alembic schema and role initialization.
- `deployment/`: systemd, Nginx, nftables and offline provisioning.
- `tests/`: application, security and destructive-operation guard tests plus isolated QEMU harness.

No live metrics are seeded. Unpolled devices are `unknown`; expired telemetry does not remain green. The 24-hour availability percentage represents observed ICMP samples, not a claim about unsampled time.
