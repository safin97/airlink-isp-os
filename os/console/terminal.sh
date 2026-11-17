#!/bin/bash
set -euo pipefail
printf '\nAirLink system terminal — ROOT ACCESS\n\n'
printf 'Commands run as root on this AirLink PC.\n'
printf 'Type exit to return to the locked PC settings panel.\n'
printf 'This terminal and its child processes close after 15 minutes.\n\n'
printf 'Update diagnostics:\n'
printf '  cat /var/lib/airlink-system/updates/state.json\n'
printf '  journalctl -u airlink-update-job.service -n 100 --no-pager\n\n'
exec /usr/bin/env -i HOME=/root USER=root LOGNAME=root SHELL=/bin/bash \
    PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
    TERM="${TERM:-xterm}" LANG=C.UTF-8 HISTFILE=/dev/null \
    PS1='AirLink root \w # ' /bin/bash --noprofile --norc -i
