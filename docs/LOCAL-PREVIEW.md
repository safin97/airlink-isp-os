# Local review login

The local preview runs the Flutter dashboard against an isolated FastAPI backend. It creates a separate SQLite database, an owner named `preview-owner`, and a random initial password. Preview data and keys are stored under the ignored `test-results/local-preview/` directory so the login and local edits survive ordinary server restarts. It does not use an inherited production database or start monitoring/payment workers.

## Run on your computer

Install a compatible Flutter SDK (the checked-in package lock uses Flutter 3.47/Dart 3.13) and Python 3.11 or newer, then run from the repository root:

```sh
./scripts/preview.sh
```

The supplied preview ZIP already includes the built dashboard. With Python 3.11 or newer installed, you can start it without installing Flutter:

```sh
./scripts/preview.sh --skip-build
```

The first launch installs the Python dependencies. Keep the terminal open while reviewing. The login and local edits persist across ordinary restarts of the same extracted project folder. If you edit Flutter source files, run the regular build workflow before reviewing those changes.

If Flutter is not on your PATH:

```sh
FLUTTER_BIN=/absolute/path/to/flutter/bin/flutter ./scripts/preview.sh
```

The script installs missing Python dependencies and builds the web dashboard. Open `http://127.0.0.1:18080/` on the same computer. Read the generated login from `test-results/local-preview-login.json`; this file is ignored by Git and has owner-only filesystem permissions. Never commit preview credentials.

To use a different local port:

```sh
./scripts/preview.sh --port 18081
```

Stop the process with Ctrl+C. Restarting reuses the local database and authentication keys. If you change your password in My account, your chosen password remains in effect; the login file records the initial password. This is still temporary workspace storage, not production hosting or a backup. Rebuilding frontend assets while keeping the server running preserves the current preview data and login.

## Managed Cloud Browser preview

In the managed workspace, the supported `sites-preview` launcher owns the server. The checkout-local, ignored `package.json` uses this development command:

```json
{"scripts":{"dev":".venv/bin/python -u tests/preview.py > test-results/managed-preview.log 2>&1"}}
```

After building the frontend and installing Python dependencies, run `sites-preview start` with the absolute checkout path. Open the exact URL returned by that command in Cloud Browser. A Cloud Browser loopback address is local to the cloud environment; it is not a public website or the localhost of your own computer.

## Available actions

The owner can review every dashboard screen and edit local accounts, permissions, inventory and saved device-login profiles. My account contains separate Account profile, Change password, Customer device access and Payment setup pages. SAS4 connection is directly below Settings in the sidebar.

Live SAS4 calls, payment operations, network discovery, device commands, appliance changes, update installation and restart are disabled. Public signed update metadata can be checked. Unpolled devices remain unknown; the preview does not invent online/offline results.

These local changes do not commit or push anything to GitHub. Review the preview before publishing code or deploying to your AirLink server.
