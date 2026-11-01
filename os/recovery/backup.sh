#!/bin/bash
set -euo pipefail
umask 077
install -d -m 0700 /var/backups/airlink
backup_dir=$(mktemp -d "/var/backups/airlink/$(date -u +%Y%m%dT%H%M%SZ)-XXXXXX")
runuser -u postgres -- pg_dump -Fc airlink > "$backup_dir/database.dump"
tar -C / -czf "$backup_dir/configuration.tar.gz" etc/airlink etc/NetworkManager/system-connections etc/nginx
(cd "$backup_dir" && sha256sum database.dump configuration.tar.gz > SHA256SUMS)
printf '%s\n' "$backup_dir"
