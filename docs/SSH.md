# SSH / PuTTY remote access

Owners can configure **Settings → SSH remote access** on installed AirLink Linux
PCs. The endpoint uses TCP **2742** and the dedicated Linux login
**airlink-admin**. SSH is disabled by default. Choose allowed client IPs/subnets,
then enter your current AirLink owner login password and choose **Enable SSH on
port 2742**. SSH and sudo use that same login password; there is no separate SSH
password field. Changing the linked owner's password through **My account →
Change password** also updates SSH. If there are several owners, SSH is linked
to the owner who last saved its settings; the linked account is shown on the page.

New images include OpenSSH. Older installed systems offer **Install SSH
component**, which installs `openssh-server` from the configured signed Debian
repositories. Installation requires internet access, healthy package state and
the shared maintenance lock. It creates an AirLink backup before package changes.
An existing failed PC update must be recovered first. Failure after package
installation starts sets the PC recovery marker. Installing the component does
not enable remote access. The distribution's default port-22 service/socket are
masked when installing the component or building a new image.

In PuTTY, enter the AirLink PC's reachable IP as **Host Name**, set **Port 2742**,
select **SSH**, and open the connection. Compare the host-key fingerprint with
the one displayed in SSH settings before accepting it. Log in as `airlink-admin`
with the linked owner's AirLink login password. For a root maintenance shell, run:

```sh
sudo -i
```

Enter that same login password when sudo asks. From an OpenSSH client:

```sh
ssh -p 2742 airlink-admin@AIRLINK_PC_IP
```

SSH provides command-line access, not screen/mouse sharing. Connections can use
the LAN, an existing VPN, or a router forwarding TCP 2742 to the appliance.
Allowed sources refer to the client address seen by AirLink after any NAT. The
initial form suggests the current browser's IP; review it for the intended SSH
client. Router port forwarding is not configured by AirLink.

The account has password-protected sudo access. Direct root login, public-key
login, empty passwords, SSH forwarding, X11 forwarding and user rc files are
disabled for this managed endpoint. Future key support requires a separate
configuration workflow. An existing unrelated `airlink-admin` OS account is
never adopted or modified automatically.
Its private home directory is `/var/lib/airlink-remote`, allowing creation without
weakening the controller's protection of `/home` and `/root`.

Enabling SSH creates a per-appliance Ed25519 host key under the root-owned
`/var/lib/airlink-system/ssh` directory and an isolated `/etc/airlink/sshd_config`.
Credentials are submitted through the owner API and Unix control socket; the
SSH password is stored only as the Linux password hash. API audit events omit
passwords. The owner password is verified before being passed to the privileged
controller to update the Linux account; it is never stored in plaintext.
Five changes/authentication attempts per owner per
five minutes are allowed. Managers cannot be delegated this feature.

During an owner password change, the linked Linux account is locked before the
database password changes and unlocked with the new password after commit.
Concurrent SSH settings changes for that owner are serialized with the password
change. If synchronization is interrupted, new SSH logins remain locked rather
than accepting an old password. The dashboard reports pending synchronization;
save SSH settings with the current login password to restore access. Existing
authenticated SSH sessions are not terminated just by changing a password.

`airlink-ssh.service` starts on boot only after owner enablement. It remains
independent of API/controller health so configured access is available for
recovery. A reserved nftables chain restricts only port 2742; other firewall
rules are preserved. The nftables service hook reapplies access after restart
or reload. Saving settings restarts SSH; disabling closes SSH sessions, locks
the managed account, removes its sudo grant and blocks the port. Owner-created
system services are not undone by disabling remote access.

Review service logs with `journalctl -u airlink-ssh.service` or component setup
logs with `journalctl -u airlink-ssh-install.service`. Local development preview
cannot install, enable or change SSH on the development host.
