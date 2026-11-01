#!/bin/bash
set -euo pipefail
apt-get update >/dev/null
apt-get install -y --no-install-recommends snmpd snmp >/dev/null
cat > /tmp/airlink-snmp-lab.conf <<'CONF'
agentaddress udp:127.0.0.1:161
createUser airlinklab SHA-256 "Lab-authentication-2026" AES "Lab-privacy-key-2026"
rouser airlinklab priv .1
CONF
snmpd -f -Lo -C -c /tmp/airlink-snmp-lab.conf > /tmp/snmp-lab.log 2>&1 &
sleep 2
/opt/airlink/venv/bin/python - <<'PY'
import asyncio,json
from monitoring.snmp import collect
values=asyncio.run(collect('127.0.0.1',{'username':'airlinklab','auth_key':'Lab-authentication-2026','priv_key':'Lab-privacy-key-2026'},1))
print(json.dumps(values,indent=2))
PY
snmpwalk -v3 -l authPriv -u airlinklab -a SHA-256 -A 'Lab-authentication-2026' -x AES -X 'Lab-privacy-key-2026' 127.0.0.1 1.3.6.1.2.1.25.3.3.1.2
