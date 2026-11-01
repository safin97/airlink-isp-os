#!/bin/bash
set -euo pipefail
case " $(cat /proc/cmdline) " in
  *' airlink.mode=recovery '*) exec xterm -fa 'DejaVu Sans Mono' -fs 13 -bg '#071426' -fg white -e /bin/bash /opt/airlink/os/recovery/shell.sh ;;
  *' airlink.mode=live '*) exec xterm -fa 'DejaVu Sans Mono' -fs 13 -bg '#071426' -fg white -e /opt/airlink/venv/bin/python /opt/airlink/os/console/console.py ;;
  *) exec /usr/bin/python3 /opt/airlink/os/installer/gui.py ;;
esac
