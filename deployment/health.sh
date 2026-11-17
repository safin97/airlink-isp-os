#!/bin/bash
set -euo pipefail
# Wait for service and worker readiness. The monitor reports a heartbeat while
# its scheduler and database are responsive, including during slow device probes.
for attempt in $(seq 1 30); do
  failures=()
  if ! curl --fail --silent --connect-timeout 1 --max-time 2 \
      http://127.0.0.1:8000/api/health >/dev/null; then
    failures+=("API/database/Redis endpoint unavailable")
  fi
  for service in nginx airlink-api airlink-monitor airlink-alerts; do
    if ! systemctl is-active --quiet "$service"; then
      failures+=("$service service is not active")
    fi
  done
  for worker in monitor alerts; do
    if ! redis-cli --raw EXISTS "health:$worker" | grep -qx 1; then
      failures+=("$worker worker heartbeat unavailable")
    fi
  done
  if [ "${#failures[@]}" -eq 0 ]; then
    printf '%s\n' 'AirLink health check passed: API, services and worker heartbeats are ready.'
    exit 0
  fi
  if [ "$attempt" -lt 30 ]; then sleep 2; fi
done
printf 'AirLink health check failed: %s\n' "${failures[@]}" >&2
exit 1
