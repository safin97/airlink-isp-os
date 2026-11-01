#!/bin/bash
# Run inside an isolated Linux builder; no physical disks are accessed.
set -euo pipefail
build_root=${1:?Usage: iso.sh BUILD_DIRECTORY}
cd "$build_root"
test -f /output/rootfs.tar
[ "$(pwd)" = /build ]
rm -rf -- rootfs image
mkdir -p rootfs image/live image/boot/grub/fonts
tar --numeric-owner --same-owner -xf /output/rootfs.tar -C rootfs
rm -f rootfs/.dockerenv rootfs/run/.containerenv
printf "airlink\n" > rootfs/etc/hostname
printf "127.0.0.1 localhost\n127.0.1.1 airlink\n::1 localhost ip6-localhost\n" > rootfs/etc/hosts
chmod 0644 rootfs/etc/hostname rootfs/etc/hosts
# Fail before packaging if ownership is lost on a shared host filesystem.
pg_uid=$(awk -F: '$1=="postgres" {print $3}' rootfs/etc/passwd)
[ "$(stat -c %u rootfs/var/lib/postgresql)" = "$pg_uid" ]
kernel=$(find rootfs/boot -maxdepth 1 -name 'vmlinuz-*' | sort -V | tail -1)
initrd=$(find rootfs/boot -maxdepth 1 -name 'initrd.img-*' | sort -V | tail -1)
test -n "$kernel" && test -n "$initrd"
cp "$kernel" image/live/vmlinuz
cp "$initrd" image/live/initrd.img
cp rootfs/opt/airlink/os/boot/grub.cfg image/boot/grub/grub.cfg
cp rootfs/usr/share/grub/unicode.pf2 image/boot/grub/fonts/unicode.pf2
cp rootfs/opt/airlink/os/build/packages.lock packages.lock
mksquashfs rootfs image/live/filesystem.squashfs -noappend -comp zstd -processors 2 -no-progress
grub-mkrescue -o AirLink-ISP-OS-amd64.iso image -- -volid AIRLINK_ISP_OS
sha256sum AirLink-ISP-OS-amd64.iso > SHA256SUMS

cp AirLink-ISP-OS-amd64.iso SHA256SUMS packages.lock /output/
mkdir -p /output/image/live
cp image/live/vmlinuz image/live/initrd.img /output/image/live/
