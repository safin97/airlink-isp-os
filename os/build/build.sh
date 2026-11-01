#!/bin/bash
set -euo pipefail
project=$(cd "$(dirname "$0")/../.." && pwd)
cd "$project"
test -f frontend/build/web/index.html || { echo 'Run flutter build web in frontend first'; exit 1; }
output=${AIRLINK_BUILD_OUTPUT:-$project/dist}
mkdir -p "$output"
output=$(cd "$output" && pwd)
version=$(sed -n 's/^__version__ = "\(.*\)"/\1/p' backend/airlink/__init__.py)
[[ "$version" =~ ^[0-9][A-Za-z0-9.+-]{0,39}$ ]] || { echo 'Invalid application version'; exit 1; }
image="airlink-isp-os:$version"
docker build --platform linux/amd64 -f os/build/Dockerfile -t "$image" .
container=$(docker create --platform linux/amd64 "$image")
trap 'docker rm "$container" >/dev/null' EXIT
docker export "$container" -o "$output/rootfs.tar"
docker run --rm --platform linux/amd64 -v airlink-iso-build:/build -v "$output:/output" -v "$project/os/build:/scripts:ro" \
  debian:trixie-slim bash -ec 'apt-get update && apt-get install -y --no-install-recommends squashfs-tools grub-common grub-pc-bin grub-efi-amd64-bin xorriso mtools && bash /scripts/iso.sh /build'
echo "ISO: $output/AirLink-ISP-OS-amd64.iso"
