# Browser system terminal

The system owner can open **Diagnostics → System terminal**, enter their current
owner password, and use an interactive root shell on the installed AirLink Linux
PC. Managers and other roles cannot use it, including users delegated Settings
or PC update access. Local preview cannot open a shell on the development host.

The terminal supports command history within the session, arrow keys, Tab,
Ctrl+C and full-screen terminal programs. It uses the dashboard's existing HTTPS
connection; there is no additional listening port or SSH password to configure.

Opening requires fresh password verification (five attempts per five minutes).
Each exchange checks the current login and owner role, and sessions are bound to
the exact login that opened them. The controller checks Unix peer credentials.
Only one root terminal can be open at a time. Opening and closing are audited;
the application does not persist typed commands, passwords or shell output.
The shell owns the shared maintenance lock: active updates must finish before
opening it, and dashboard updates wait until it closes. Failed updates remain
accessible for recovery review.

Closing the dialog stops the shell and its children. Lost connections expire
after 90 seconds without a successful exchange. Sessions have a 15-minute hard
limit enforced by systemd, and controller shutdown also stops the shell unit.
Do not use this bounded terminal for long unattended jobs. Starting a system
update or restarting the API/controller may disconnect the terminal.

For PC update diagnosis, these commands only read current state:

```sh
cat /var/lib/airlink-system/pc-updates/state.json
systemctl status airlink-pc-update-install.service --no-pager
journalctl -u airlink-pc-update-install.service -n 60 --no-pager
dpkg --audit
```

Review the output before repairing an interrupted update. Opening a terminal
does not clear recovery state or bypass package update locks.
