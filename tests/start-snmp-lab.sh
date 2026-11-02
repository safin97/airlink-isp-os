#!/bin/bash
set -euo pipefail
apt-get update >/dev/null
apt-get install -y --no-install-recommends snmpd snmp >/dev/null
cat > /tmp/airlink-snmp-lab.conf <<'CONF'
agentaddress udp:127.0.0.1:161
createUser airlinklab SHA-256 "Lab-authentication-2026" AES "Lab-privacy-key-2026"
rouser airlinklab priv .1
rocommunity airlink-read-only-lab 127.0.0.1 .1
CONF
snmpd -f -Lo -C -c /tmp/airlink-snmp-lab.conf > /tmp/snmp-lab.log 2>&1 &
sleep 2
/opt/airlink/venv/bin/python tests/snmp_lab.py
