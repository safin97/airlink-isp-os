#!/bin/bash
set -euo pipefail
for attempt in $(seq 1 30); do
  if curl --fail --silent http://127.0.0.1:8000/api/health >/dev/null; then break; fi
  sleep 2
done
curl --fail --silent http://127.0.0.1:8000/api/health
systemctl is-active nginx airlink-api airlink-monitor airlink-alerts
redis-cli EXISTS health:monitor | grep -qx 1
redis-cli EXISTS health:alerts | grep -qx 1
