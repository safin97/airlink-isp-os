# Installed PC settings panel

The local display opens **PC settings** automatically on installed AirLink systems running 0.1.4-dev or later. Use the same owner account as the web dashboard. On a fresh system, create the first owner here; there is no default password. DHCP and local owner creation work without an Internet connection.

- **Overview:** current hostname, dashboard addresses, CPU, memory, storage and service status.
- **Network:** select the Ethernet interface, DHCP or static IPv4, address, subnet prefix (24) or mask (255.255.255.0), gateway and up to two DNS servers. Apply, verify connectivity, then choose **Keep settings** within 120 seconds. **Revert settings** restores the previous connection immediately. NetworkManager owns the automatic rollback, even if the panel or API stops.
- **Hostname & time:** hostname, timezone selector, optional manual local date/time (`YYYY-MM-DD HH:MM:SS`). Enter manual time in the selected timezone; leave it empty to keep the clock. Automatic synchronization is available only when a supported NTP service is installed. The current development ISO does not include that service; the panel clearly reports this and permits manual time/timezone changes. Clock changes can invalidate sessions and affect scheduled updates.
- **Updates:** check GitHub, download and verify, install, schedule with an explicit timezone offset, and restart the system. All packages use the existing signed feed and replay protection. Refresh status to follow installation. The panel may restart as part of an update.
- **Backups:** create local backups, select an existing backup and restore its database after confirmation. Restore replaces current records and first creates a safety backup. Configuration archives are retained for manual recovery review; they are not silently restored. Copy backups off the appliance as well.
- **Logs:** view the latest 100 relevant service journal entries.
- **System:** restart AirLink services, restart or shut down the PC, with confirmation and update-operation guards.

The panel locks after five minutes without user input. Each local privileged action rechecks the live owner session; network and update actions also use owner-protected APIs. Local maintenance is serialized against the updater. Closing the panel does not expose a root shell. Recovery remains available from the installer media.

## Existing installations

Install the signed 0.1.4-dev update through Software Updates. The package replaces the installed console service with the graphical panel and starts it automatically. Existing owner accounts, network configuration, monitoring data and secrets remain intact. The published 0.1.2-dev ISO still installs the older console; applying this update enables the panel. This application release does not rebuild the ISO or upgrade the kernel/base OS.
