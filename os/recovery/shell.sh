#!/bin/bash
set -euo pipefail
printf '\nAirLink ISP OS — Local Recovery\n\n'
cat /opt/airlink/docs/RECOVERY.md
printf '\nType RECOVERY to open a local root recovery shell: '
read -r confirmation
[ "$confirmation" = RECOVERY ] || exit 1
export PS1='AirLink recovery \w # '
exec /bin/bash --noprofile --norc
