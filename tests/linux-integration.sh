#!/bin/bash
set -euo pipefail
/opt/airlink/venv/bin/pip install pytest 'fakeredis[lua]'
pg_lsclusters --no-header | while read -r version name rest; do
  pg_ctlcluster --skip-systemctl-redirect "$version" "$name" start
 done
runuser -u postgres -- createuser --no-superuser --no-createdb --no-createrole airlink
runuser -u postgres -- createdb -O airlink airlink
export DATABASE_URL=postgresql+psycopg://airlink@/airlink
export AIRLINK_TEST_DATABASE_URL="$DATABASE_URL"
export PYTHONPATH=/opt/airlink/backend:/opt/airlink:/opt/airlink/os
cd /opt/airlink
runuser -u airlink --preserve-environment -- /opt/airlink/venv/bin/alembic -c database/alembic.ini upgrade head
runuser -u airlink -- psql airlink -v ON_ERROR_STOP=1 -c 'SELECT * FROM roles;'
runuser -u airlink --preserve-environment -- /opt/airlink/venv/bin/alembic -c database/alembic.ini check
runuser -u airlink --preserve-environment -- /opt/airlink/venv/bin/python -m pytest -q -o python_files=test_*.py -p no:cacheprovider /tests
apt-get update
apt-get install -y --no-install-recommends snmpd
cat > /tmp/airlink-snmp-lab.conf <<'CONF'
agentaddress udp:127.0.0.1:161
createUser airlinklab SHA-256 "Lab-authentication-2026" AES "Lab-privacy-key-2026"
rouser airlinklab priv .1
CONF
snmpd -f -Lo -C -c /tmp/airlink-snmp-lab.conf > /tmp/snmp-lab.log 2>&1 &
sleep 2
/opt/airlink/venv/bin/python /tests/snmp_lab.py
