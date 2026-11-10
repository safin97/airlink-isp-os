#!/bin/bash
set -euo pipefail
if [ "$#" != 2 ] || [ "$2" != RESTORE ]; then
  echo 'Usage: restore.sh /var/backups/airlink/TIMESTAMP RESTORE (replaces the database)'; exit 2
fi
backup_dir=$(realpath "$1")
case "$backup_dir" in /var/backups/airlink/*) ;; *) echo 'Backup must be in the protected backup directory'; exit 2;; esac
(cd "$backup_dir" && sha256sum -c SHA256SUMS)
# Share the maintenance lock with updates and automatic cloud backups.
if [ -z "${AIRLINK_MAINTENANCE_FD:-}" ]; then
  install -d -m 0700 /var/lib/airlink-system/updates
  exec 9>/var/lib/airlink-system/updates/lock
  AIRLINK_MAINTENANCE_FD=9
fi
# The authenticated panel passes its already-held lock to this child process.
flock -n "$AIRLINK_MAINTENANCE_FD" || { echo 'An update or backup is running. Retry recovery when it finishes.'; exit 1; }
restart_on_exit() {
  result=$?
  trap - EXIT
  systemctl start airlink-api airlink-monitor airlink-alerts || result=1
  exit "$result"
}
trap restart_on_exit EXIT
systemctl stop airlink-api airlink-monitor airlink-alerts
/bin/bash /opt/airlink/os/recovery/backup.sh
runuser -u postgres -- pg_restore --clean --if-exists --exit-on-error --single-transaction -d airlink < "$backup_dir/database.dump"
# Secrets and network files are restored only after local review; never silently overwrite connectivity.
systemctl start airlink-api airlink-monitor airlink-alerts
trap - EXIT
/bin/bash /opt/airlink/deployment/health.sh
