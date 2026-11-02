FROM --platform=linux/amd64 debian:trixie-slim@sha256:f6b08b09a05725f9431502d3b5714f5c4576e82c1a84fa1debe0c24a7e0c3ec4 AS foundation
ENV DEBIAN_FRONTEND=noninteractive
RUN printf '#!/bin/sh\nexit 101\n' > /usr/sbin/policy-rc.d && chmod +x /usr/sbin/policy-rc.d && \
    sed -i 's/Components: main/Components: main contrib non-free non-free-firmware/' /etc/apt/sources.list.d/debian.sources && \
    apt-get update && apt-get install -y --no-install-recommends \
    linux-image-amd64 live-boot live-config live-tools systemd-sysv dbus udev initramfs-tools \
    grub-efi-amd64-bin grub2-common efibootmgr gdisk parted dosfstools e2fsprogs squashfs-tools \
    network-manager iproute2 iputils-ping dnsutils nftables curl ca-certificates openssl \
    postgresql redis-server nginx python3 python3-venv python3-pip python3-pyqt6 python3-dbus \
    python3-psutil python3-cryptography xserver-xorg xinit openbox xterm fonts-dejavu \
    firmware-linux-free firmware-realtek firmware-iwlwifi sudo less locales rsync procps && \
    apt-get clean && rm -rf /var/lib/apt/lists/*
RUN useradd --system --home-dir /var/lib/airlink --create-home --shell /usr/sbin/nologin airlink && \
    mkdir -p /etc/airlink /var/lib/airlink /var/backups/airlink /opt/airlink && \
    passwd -l root && printf 'en_US.UTF-8 UTF-8\n' > /etc/locale.gen && locale-gen
FROM foundation AS graphics
COPY os/build/install-gpu-drivers.sh /tmp/install-gpu-drivers.sh
RUN bash /tmp/install-gpu-drivers.sh && rm /tmp/install-gpu-drivers.sh
FROM graphics AS runtime
COPY backend/requirements.lock /tmp/requirements.lock
RUN python3 -m venv /opt/airlink/venv && /opt/airlink/venv/bin/pip install --no-cache-dir -r /tmp/requirements.lock
COPY backend /opt/airlink/backend
COPY database /opt/airlink/database
COPY monitoring /opt/airlink/monitoring
COPY os /opt/airlink/os
COPY deployment /opt/airlink/deployment
COPY docs /opt/airlink/docs
COPY tests/guest_install.py /opt/airlink/tests/guest_install.py
COPY frontend/build/web /opt/airlink/frontend/build/web
RUN cp /opt/airlink/deployment/systemd/* /etc/systemd/system/ && \
    cp /opt/airlink/deployment/nginx.conf /etc/nginx/sites-available/airlink && \
    rm -f /etc/nginx/sites-enabled/default && ln -s /etc/nginx/sites-available/airlink /etc/nginx/sites-enabled/airlink && \
    cp /opt/airlink/deployment/nftables.conf /etc/nftables.conf && \
    printf 'bind 127.0.0.1 ::1\nprotected-mode yes\nport 6379\nsupervised systemd\ndaemonize no\ndir /var/lib/redis\n' > /etc/redis/redis.conf && \
    chown redis:redis /etc/redis/redis.conf && \
    printf '[main]\nplugins=keyfile\n[ifupdown]\nmanaged=true\n' > /etc/NetworkManager/NetworkManager.conf && \
    mkdir -p /etc/network && printf 'auto lo\niface lo inet loopback\n' > /etc/network/interfaces && \
    sed -i "s/^#*listen_addresses =.*/listen_addresses = ''/" /etc/postgresql/*/main/postgresql.conf && \
    systemctl enable NetworkManager nftables postgresql redis-server nginx airlink-api airlink-monitor airlink-alerts airlink-controller airlink-console airlink-live-init airlink-installer airlink-qa airlink-health.timer && \
    chmod +x /opt/airlink/os/build/graphical-session.sh && systemctl mask getty@tty1.service live-config.service && \
    version=$(PYTHONPATH=/opt/airlink/backend /opt/airlink/venv/bin/python -c 'from airlink import __version__; print(__version__)') && \
    printf 'NAME="AirLink ISP OS"\nID=airlink\nID_LIKE=debian\nPRETTY_NAME="AirLink ISP OS %s"\nVERSION_ID="%s"\n' "$version" "$version" > /etc/os-release && \
    printf 'AirLink ISP OS — Network Monitoring Operating System\n' > /etc/issue && \
    rm -f /usr/sbin/policy-rc.d /etc/machine-id /var/lib/dbus/machine-id && \
    touch /etc/machine-id && update-initramfs -u -k all && \
    dpkg-query -W > /opt/airlink/os/build/packages.lock
CMD ["/sbin/init"]
