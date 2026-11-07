#!/usr/bin/env bash
set -euo pipefail
preview_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$preview_root"
preview_build=1
if [[ "${1:-}" == "--skip-build" ]]; then
  preview_build=0
  shift
fi
if [[ ! -x .venv/bin/python ]]; then
  python3 -m venv .venv
fi
if ! .venv/bin/python -c 'import fastapi, fakeredis, uvicorn' >/dev/null 2>&1; then
  .venv/bin/python -m pip install -r backend/requirements.lock 'fakeredis[lua]'
fi
if [[ "$preview_build" == 1 ]]; then
  preview_flutter="${FLUTTER_BIN:-flutter}"
  (
    cd frontend
    CI=true "$preview_flutter" pub get
    CI=true "$preview_flutter" build web --release --no-web-resources-cdn --dart-define=API_BASE=
  )
elif [[ ! -f frontend/build/web/index.html ]]; then
  printf '%s\n' 'Built dashboard missing. Run without --skip-build to build it first.' >&2
  exit 1
fi
if [[ "${SITES_MANAGED_LINUX_CONTAINER:-}" == 1 ]]; then
  exec sites-preview start "$preview_root"
fi
exec .venv/bin/python -u tests/preview.py "$@"
