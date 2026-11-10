# Run AirLink locally in VS Code

The local application is available at **http://127.0.0.1:18080/**. It uses the saved local database and accounts. The Mac's internet connection is used for outgoing SAS4 and device requests; no public hosting or port forwarding is needed.

## Live mode

In the repository's VS Code terminal, run:

```sh
./scripts/live.sh
```

Equivalent: `make live`. This uses the existing web build, enables real SAS4 calls and polls enabled inventory devices in the background using their saved ICMP, SNMP and device API settings. Online-user snapshots and customer telemetry refresh even when no page is open. The terminal prints `AirLink local mode: LIVE` at startup. Keep the process running while using the app; Ctrl+C stops it.

Use **SAS4 connection** to save your real SAS4 login for your local account. Existing real connections are preserved. Live mode removes only the exact synthetic SAS4 connection fixtures originally created by the demo launcher; it preserves their accounts. It never replaces live readings with sample online-user data. Saved private device IPs still need a working LAN or VPN route from the Mac; internet access alone cannot reach an isolated tower subnet.

The server binds only to `127.0.0.1`. It is a local development runtime using SQLite and an in-process Redis substitute, not the installed Linux appliance. Automatic payment processing and outbound alert dispatch are not started by this local launcher. Appliance networking, OS updates/restarts and scheduled Google Drive archive creation require the installed Linux system.

## Build changes or use demo mode

After editing Flutter code, build and start live mode with:

```sh
FLUTTER_BIN='/absolute/path/to/flutter/bin/flutter' ./scripts/preview.sh --live
```

For demo SAS4 data without background device polling:

```sh
./scripts/preview.sh --skip-build
```

Omit `--skip-build` to rebuild the dashboard first. Stop the existing local process before starting another on the same port. Use `./scripts/live.sh --port 18081` for another port, but do not run multiple live monitors against the same local database.

## Local data and login

The current launcher stores data in `/tmp/airlink-browser-qa.sqlite`. It reuses existing accounts, passwords, inventory and credential profiles on restart. If there is no existing database, it initializes the development owner defined in `tests/preview.py`. A restart refreshes local session signing keys; the browser can refresh a saved session or you can sign in again with your existing local account.

This `/tmp` database is temporary development storage and should be backed up before cleanup or reinstalling the Mac. Before the first switch to live mode, the existing database was copied to `/tmp/airlink-browser-qa-before-live-20261110T084432Z.sqlite`. It includes the previous readings and demo connection state. Keep database copies private because they include account data and encrypted device credentials.

The live launcher does not publish to GitHub or change your separate installed AirLink server. Internet, routing and authentication failures are shown as actual errors or unavailable readings; check the local terminal log and the relevant saved connection settings.
