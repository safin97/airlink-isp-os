#!/bin/bash
# Run in the built amd64 image. This packages application code, not a kernel upgrade.
set -euo pipefail
version=${1:?Usage: build-package.sh VERSION OUTPUT_DIRECTORY}
output=${2:?Output directory required}
[[ "$version" =~ ^[0-9][A-Za-z0-9.+~-]{0,39}$ ]] || { echo 'Invalid Debian version'; exit 2; }
runtime_version=$(PYTHONPATH=/opt/airlink/backend /opt/airlink/venv/bin/python -c 'from airlink import __version__; print(__version__)')
[ "$version" = "$runtime_version" ] || { echo 'Package version must match the built application'; exit 2; }
stage=$(mktemp -d)
trap 'rm -rf "$stage"' EXIT
mkdir -p "$stage/DEBIAN" "$stage/opt"
cp -a /opt/airlink "$stage/opt/airlink"
cat > "$stage/DEBIAN/control" <<CONTROL
Package: airlink-isp-os
Version: $version
Architecture: amd64
Maintainer: AirLink Release Engineering
Depends: python3 (>= 3.13), postgresql, redis-server, nginx
Description: AirLink ISP OS application and monitoring services
CONTROL
cat > "$stage/DEBIAN/postinst" <<'POSTINST'
#!/bin/sh
set -eu
if [ "$1" = configure ] && [ -f /etc/airlink/installed ]; then
  bash /opt/airlink/os/branding/install-boot-theme.sh
fi
if [ "$1" = configure ] && [ -d /run/systemd/system ]; then
  systemctl daemon-reload
  # The previous updater restarts API/workers; reload long-lived control code too.
  systemctl try-restart airlink-controller.service airlink-console.service
fi
POSTINST
chmod 0755 "$stage/DEBIAN/postinst"
# System integration files are installed by the signed package, under fixed paths.
mkdir -p "$stage/etc/systemd/system"
cp /opt/airlink/deployment/systemd/airlink-{api,monitor,alerts,controller,console,health,update-job}.service "$stage/etc/systemd/system/"
cp /opt/airlink/deployment/systemd/airlink-health.timer "$stage/etc/systemd/system/"
mkdir -p "$output"
dpkg-deb --root-owner-group --build "$stage" "$output/airlink-isp-os_${version}_amd64.deb"
