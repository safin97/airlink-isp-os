#!/bin/bash
set -euo pipefail
set -a
source /etc/airlink/airlink.env
set +a
cd /opt/airlink
runuser -u airlink --preserve-environment -- /opt/airlink/venv/bin/alembic -c database/alembic.ini upgrade head
