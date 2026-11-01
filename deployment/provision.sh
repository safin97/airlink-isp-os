#!/bin/bash
# Idempotent, offline provisioning, called only within the new target or live overlay.
set -euo pipefail
umask 077
bash /opt/airlink/os/branding/install-boot-theme.sh
install -d -m 0750 -o root -g airlink /etc/airlink
install -d -m 0750 -o airlink -g airlink /var/lib/airlink
install -d -m 0700 /var/backups/airlink /var/lib/airlink-system
install -d -m 2775 -o postgres -g postgres /run/postgresql
# Seed publisher trust for new installations; preserve any configured site's source.
if [ ! -f /etc/airlink/update-source.json ] || [ ! -f /etc/airlink/update-public-key.bin ]; then
  if [ -f /opt/airlink/deployment/update-source/update-source.json ]; then
    /opt/airlink/venv/bin/python /opt/airlink/os/updates/install_source.py
  fi
fi
if [ ! -f /etc/airlink/airlink.env ]; then
  /opt/airlink/venv/bin/python - <<'PY'
import secrets
from pathlib import Path
from cryptography.fernet import Fernet
Path('/etc/airlink/airlink.env').write_text(
    'DATABASE_URL=postgresql+psycopg://airlink@/airlink\n'
    'REDIS_URL=redis://127.0.0.1:6379/0\n'
    'AIRLINK_SECURE_COOKIES=true\n'
    'PYTHONPATH=/opt/airlink/backend:/opt/airlink\n'
    'AIRLINK_JWT_SECRET=' + secrets.token_urlsafe(64) + '\n'
    'AIRLINK_ENCRYPTION_KEY=' + Fernet.generate_key().decode() + '\n'
    'AIRLINK_BOOTSTRAP_TOKEN=' + secrets.token_urlsafe(36) + '\n')
PY
  chown root:airlink /etc/airlink/airlink.env
  chmod 0640 /etc/airlink/airlink.env
fi
if [ ! -f /etc/airlink/tls.key ]; then
  openssl req -x509 -nodes -newkey rsa:3072 -days 365 -keyout /etc/airlink/tls.key -out /etc/airlink/tls.crt \
    -subj '/CN=airlink.local/O=AirLink ISP OS' -addext 'subjectAltName=DNS:airlink.local,DNS:airlink'
fi
# PostgreSQL uses local peer authentication; no database passwords are embedded.
cluster=$(pg_lsclusters --no-header | awk 'NR==1 {print $1 " " $2}')
read -r pgversion pgname <<< "$cluster"
[ -n "$pgversion" ]
pg_ctlcluster --skip-systemctl-redirect "$pgversion" "$pgname" start || pg_ctlcluster --skip-systemctl-redirect "$pgversion" "$pgname" status
if ! runuser -u postgres -- psql -tAc "SELECT 1 FROM pg_roles WHERE rolname='airlink'" | grep -q 1; then
  runuser -u postgres -- createuser --no-superuser --no-createdb --no-createrole airlink
fi
if ! runuser -u postgres -- psql -tAc "SELECT 1 FROM pg_database WHERE datname='airlink'" | grep -q 1; then
  runuser -u postgres -- createdb -O airlink airlink
fi
/bin/bash /opt/airlink/deployment/migrate.sh
nginx -t
systemctl enable postgresql redis-server nginx NetworkManager nftables airlink-api airlink-monitor airlink-alerts airlink-controller airlink-console airlink-health.timer
pg_ctlcluster --skip-systemctl-redirect "$pgversion" "$pgname" stop
touch /etc/airlink/provisioned
