#!/bin/bash
# Install only AirLink's theme; keep the site's other GRUB settings intact.
set -euo pipefail
source_dir=$(cd "$(dirname "$0")" && pwd)
install -d -m 0755 /boot/grub/themes/airlink /etc/default/grub.d
install -m 0644 "$source_dir/grub/theme.txt" /boot/grub/themes/airlink/theme.txt
install -m 0644 "$source_dir/airlink-horizontal.png" /boot/grub/themes/airlink/airlink-horizontal.png
cat > /etc/default/grub.d/airlink-theme.cfg <<'GRUB'
GRUB_THEME="/boot/grub/themes/airlink/theme.txt"
GRUB_GFXMODE="1024x768,auto"
GRUB_TERMINAL_OUTPUT="gfxterm"
GRUB
if [ -f /boot/grub/grub.cfg ]; then
  update-grub
fi
