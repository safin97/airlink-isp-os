#!/bin/bash
set -euo pipefail
if [ ! -f /etc/airlink/provisioned ]; then
  /bin/bash /opt/airlink/deployment/provision.sh
fi
pg_lsclusters --no-header | while read -r version name rest; do
  pg_ctlcluster --skip-systemctl-redirect "$version" "$name" start || pg_ctlcluster --skip-systemctl-redirect "$version" "$name" status
done
systemctl start redis-server
echo 'AIRLINK_LIVE_READY' > /dev/ttyS0 || true
