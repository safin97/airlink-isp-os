#!/usr/bin/env bash
# Live local development: real saved SAS4 connections and background device polling.
set -euo pipefail
live_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
exec bash "$live_root/scripts/preview.sh" --skip-build --live "$@"
