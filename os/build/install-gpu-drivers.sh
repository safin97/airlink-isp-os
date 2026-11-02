#!/bin/bash
# Image-build step only: drivers are present before the ISO boots, including offline.
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
repository=https://developer.download.nvidia.com/compute/cuda/repos/debian13/x86_64
keyring=/tmp/airlink-nvidia-keyring.deb
curl --fail --location --proto '=https' --tlsv1.2 "$repository/cuda-keyring_1.1-1_all.deb" -o "$keyring"
printf '%s  %s\n' d0d4ef986a44400f9db33c600ef33a985175e7cc63d805a10e1839c7a1e78f5f "$keyring" | sha256sum -c -
dpkg -i "$keyring"
apt-get update
apt-get install -y --no-install-recommends nvidia-driver-pinning-610
# NVIDIA's open kernel module supports RTX/Turing and newer; retain Mesa for other GPUs.
apt-get install -y --no-install-recommends linux-headers-amd64 nvidia-open \
    pciutils mesa-utils libgl1-mesa-dri
command -v nvidia-smi
for modules in /lib/modules/*; do
    kernel=${modules##*/}
    test -f "/boot/vmlinuz-$kernel" || continue
    dkms autoinstall -k "$kernel"
    depmod "$kernel"
    test "$(modinfo -k "$kernel" -F version nvidia)" != ''
done
printf 'options nvidia-drm modeset=1\n' > /etc/modprobe.d/airlink-nvidia.conf
# Do not distribute the image builder's module-signing private key.
rm -f /var/lib/dkms/mok.key "$keyring"
apt-get clean
rm -rf /var/lib/apt/lists/*
