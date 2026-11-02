# Installation and first boot

## Hardware

Compatible x86_64 UEFI PC, 4 GB RAM minimum (8 GB recommended), 32 GiB target disk minimum (64 GB SSD recommended), supported Ethernet adapter, display and keyboard. Capacity and poll rate determine storage/CPU needs. Test your NIC/storage controller before committing a machine. Standard Debian kernel drivers and Intel/Realtek firmware are included; proprietary hardware may need additional firmware and licensing review.

This development image uses a custom GRUB boot chain. **Disable Secure Boot.** Signed kernels alone do not establish a signed custom ISO chain. Secure Boot with enrolled keys/shim is not validated. BIOS compatibility is incidental to GRUB rescue image construction; the installer deliberately requires UEFI.

## Prepare and boot

1. Verify the ISO against `SHA256SUMS` (this detects corruption; it is not publisher authentication).
2. Write the ISO to a spare USB of at least 2 GB with a reputable image-writing tool. Select that USB carefully: writing an image destroys its existing content.
3. Boot the PC's UEFI USB entry. Choose Install, Try Live, Recovery, or Advanced Options.
4. In the installer, review the exact disk path, model, serial and capacity. Mounted disks, installer media, swap, active mappings and read-only devices are excluded. Unmount unrelated filesystems manually only after understanding why they were protected.
5. Acknowledge data destruction and type `ERASE`. Installation creates a 512 MiB EFI partition and an ext4 root partition on that disk only. Application packages, database, web assets and drivers are already present in the offline image.
6. Wait for the verification result. Errors are displayed and logged in `/var/log/airlink-installer.log`; failure does not show a successful completion state.
7. Restart and remove the USB. The local AirLink console starts automatically. If firmware selects another disk, choose the installed AirLink drive in its UEFI boot menu; installation uses the selected disk’s EFI fallback path without changing unrelated boot entries.

## First boot

DHCP starts automatically. The console offers a network wizard before owner creation. Static IPv4 requires an interface, host address, prefix, gateway, DNS and hostname. Changes use a 120-second NetworkManager checkpoint. Confirm with `KEEP` locally, or reconnect at the new address and use Keep Configuration in the web settings. Without confirmation, NetworkManager restores the previous connection even if the API crashes. Only one pending configuration is permitted.

Create the first owner with a 14–128 character password containing at least eight distinct characters. Passwords are hashed with Argon2id. The initialization singleton prevents a second first-owner creation. Remote initial setup additionally requires the random token stored in the root-controlled `/etc/airlink/airlink.env`; prefer the physical console.

The console shows server addresses and service health. Open `https://SERVER-IP/` from a browser. A new self-signed certificate is generated per installation. Verify its fingerprint locally (`openssl x509 -in /etc/airlink/tls.crt -noout -fingerprint -sha256`) before trusting it, or replace it with a trusted LAN/domain certificate. HTTP redirects to HTTPS. Do not enter passwords over plain HTTP.

## Remote access

Use a configured HTTPS DNS name and a trusted certificate, or route access over an administrator-configured VPN. Configure the certificate/key paths in Nginx and run `nginx -t` before reloading. VPN enrollment, DNS records and ACME credentials are site-specific and are not auto-created. Do not expose ports 5432, 6379, 8000 or SNMP management to the internet. The firewall permits inbound web traffic and essential ICMP/DHCP; databases and cache are local only. SSH is not enabled.

## VM testing

Use a dedicated 40 GiB virtual target disk and a separate protected disk; never pass host block devices through to the VM. The explicit QA harness checks the VM SMBIOS identity and disk serials before selecting a target. It does not bypass the installer identity/mount checks. Boot-menu and graphical review are separate from the unattended install exercise. Consult the test-results directory and PROGRESS.md for actual outcomes.

Unconfirmed network profiles have autoconnect disabled. A reboot during the confirmation window therefore leaves the previous automatic connection eligible to start. Autoconnect is enabled for the new profile only after the owner explicitly confirms it.

## Local-IP HTTPS after application update 0.1.8

Open `https://YOUR-AIRLINK-PC-IP`. HTTP redirects to HTTPS. The device's self-signed certificate contains current IP addresses and is maintained on startup/update; browsers must trust the device certificate or explicitly accept it after verifying the PC. A private IP cannot obtain a public-domain certificate through this feature. Operator-installed certificates are preserved. After changing the PC's IP, restart it to refresh its managed certificate. HTTPS dashboard assets revalidate so a browser refresh loads the installed version.
