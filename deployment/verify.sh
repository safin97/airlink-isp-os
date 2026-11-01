#!/bin/bash
set -euo pipefail
test -f /etc/airlink/provisioned
test -s /etc/airlink/airlink.env
test -f /opt/airlink/frontend/build/web/index.html
test -x /usr/sbin/nginx
test -x /usr/bin/redis-server
test -x /usr/sbin/nft
test -x /usr/bin/nmcli
PYTHONPATH=/opt/airlink/backend:/opt/airlink /opt/airlink/venv/bin/python -c \
  'import airlink.api, monitoring.worker, sqlalchemy, psycopg, redis; from argon2 import PasswordHasher; from pysnmp.hlapi.v3arch.asyncio import SnmpEngine'
nginx -t
for service in airlink-api airlink-monitor airlink-alerts airlink-controller airlink-console; do
  systemctl is-enabled "$service"
done
cluster=$(pg_lsclusters --no-header | awk 'NR==1 {print $1 " " $2}')
read -r version name <<< "$cluster"
pg_ctlcluster --skip-systemctl-redirect "$version" "$name" start
trap 'pg_ctlcluster --skip-systemctl-redirect "$version" "$name" stop' EXIT
runuser -u airlink -- psql airlink -v ON_ERROR_STOP=1 -c 'SELECT version_num FROM alembic_version;' -c 'SELECT count(*) FROM roles;'
echo 'AIRLINK_TARGET_COMPONENTS_VERIFIED'
