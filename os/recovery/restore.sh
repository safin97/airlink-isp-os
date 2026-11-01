#!/bin/bash
set -euo pipefail
if [ "$#" != 2 ] || [ "$2" != RESTORE ]; then
  echo 'Usage: restore.sh /var/backups/airlink/TIMESTAMP RESTORE (replaces the database)'; exit 2
fi
backup_dir=$(realpath "$1")
case "$backup_dir" in /var/backups/airlink/*) ;; *) echo 'Backup must be in the protected backup directory'; exit 2;; esac
(cd "$backup_dir" && sha256sum -c SHA256SUMS)
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
