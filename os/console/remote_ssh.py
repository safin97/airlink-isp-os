"""Owner-configured OpenSSH endpoint on port 2742, independent of dashboard health."""
import ipaddress
import json
import os
from pathlib import Path
import pwd
import secrets
import subprocess
import sys
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from updates import update, pc

ROOT = Path('/var/lib/airlink-system/ssh')
CONFIG = Path('/etc/airlink/sshd_config')
SUDOERS = Path('/etc/sudoers.d/airlink-remote')
HOME = Path('/var/lib/airlink-remote')
SSHD = Path('/usr/sbin/sshd')
PORT = 2742
USER = 'airlink-admin'
UNIT = 'airlink-ssh.service'
INSTALL_UNIT = 'airlink-ssh-install.service'
LOCK = threading.RLock()


def installed():
    return sys.platform == 'linux' and Path('/etc/airlink/installed').exists()


def run(args, *, secret=None, timeout=20, ok=(0,)):
    result = subprocess.run(args, input=secret, capture_output=True, text=True, timeout=timeout)
    if result.returncode not in ok:
        # In particular, never include chpasswd input, shadow data or credentials.
        raise ValueError('SSH setup could not complete. Review the airlink-controller or airlink-ssh service journal.')
    return result.stdout.strip()


def read():
    return update.read(ROOT / 'settings.json', {'enabled': False, 'sources': []})


def sources(values):
    if not isinstance(values, list) or not 1 <= len(values) <= 32:
        raise ValueError('Enter 1–32 allowed client IP addresses or subnets')
    networks = []
    for value in values:
        try:
            if not isinstance(value, str):
                raise ValueError()
            network = ipaddress.ip_network(value.strip(), strict=False)
            if network.is_multicast or network.is_loopback or network.is_link_local:
                raise ValueError()
        except ValueError:
            raise ValueError('Use client IP addresses or subnets, such as 192.168.1.0/24') from None
        networks.append(network)
    # Collapse overlap before generating firewall rules.
    return [str(net) for version in (4, 6) for net in
            ipaddress.collapse_addresses(n for n in networks if n.version == version)]


def validate_password(value):
    if (not isinstance(value, str) or not 14 <= len(value) <= 128 or len(set(value)) < 8 or
            any(ord(c) < 32 or ord(c) == 127 for c in value)):
        raise ValueError('Use an SSH password of 14–128 characters with at least 8 distinct characters')
    return value


def write_file(path, content, mode=0o600):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.new')
    # Never reuse a preexisting symlink for privileged file writes.
    temporary.unlink(missing_ok=True)
    with temporary.open('x') as stream:
        os.chmod(temporary, mode)
        stream.write(content)
    temporary.replace(path)


def firewall(settings=None):
    """Only touch the reserved SSH chain/jump; preserve all other firewall rules."""
    settings = read() if settings is None else settings
    value = json.loads(run(['nft', '-j', '-a', 'list', 'table', 'inet', 'airlink']))
    entries = value.get('nftables', [])
    chain_exists = any(e.get('chain', {}).get('name') == 'airlink_ssh' for e in entries)
    jumps = [e['rule'] for e in entries if e.get('rule', {}).get('chain') == 'input' and
             e['rule'].get('comment') == 'AirLink SSH access']
    script = [] if chain_exists else ['add chain inet airlink airlink_ssh']
    script.append('flush chain inet airlink airlink_ssh')
    if settings.get('enabled'):
        for network in sources(settings.get('sources')):
            family = 'ip6' if ':' in network else 'ip'
            script.append(f'add rule inet airlink airlink_ssh {family} saddr {network} accept')
    script.append('add rule inet airlink airlink_ssh drop')
    # Put the gate before established-connection rules, including on older images.
    for rule in jumps:
        script.append(f'delete rule inet airlink input handle {int(rule["handle"])}')
    script.append(f'insert rule inet airlink input tcp dport {PORT} jump airlink_ssh comment "AirLink SSH access"')
    run(['nft', '-f', '-'], secret='\n'.join(script) + '\n')


def managed_account(create=False):
    marker = update.read(ROOT / 'account.json', None)
    try:
        account = pwd.getpwnam(USER)
    except KeyError:
        if not create:
            return None
        if marker:
            raise ValueError('The managed SSH account is missing; review it locally before recreating it')
        if HOME.exists() or HOME.is_symlink():
            raise ValueError('The SSH home directory already exists outside AirLink SSH settings; review it locally')
        # The controller intentionally has ProtectHome=yes. Keep the dedicated
        # account home outside /home and /root instead of weakening that sandbox.
        run(['useradd', '--create-home', '--home-dir', str(HOME), '--shell', '/bin/bash', USER])
        HOME.chmod(0o700)
        account = pwd.getpwnam(USER)
        update.atomic(ROOT / 'account.json', {'uid': account.pw_uid})
        marker = {'uid': account.pw_uid}
    if not marker or marker.get('uid') != account.pw_uid or account.pw_uid == 0:
        raise ValueError('The airlink-admin account already exists outside AirLink SSH settings; review it locally')
    return account


def stop():
    run(['systemctl', 'disable', '--now', UNIT])
    account = managed_account()
    if account:
        run(['usermod', '--lock', USER])
        run(['loginctl', 'terminate-user', USER], ok=(0, 1))
    SUDOERS.unlink(missing_ok=True)


def configuration():
    return f'''# Managed by AirLink SSH settings. Separate from the distribution ssh service.
Port {PORT}
AddressFamily any
HostKey {ROOT}/host_ed25519
PidFile /run/airlink-ssh/sshd.pid
AllowUsers {USER}
PermitRootLogin no
PasswordAuthentication yes
KbdInteractiveAuthentication no
PubkeyAuthentication no
PermitEmptyPasswords no
UsePAM yes
StrictModes yes
LoginGraceTime 30
MaxAuthTries 3
MaxStartups 3:50:10
DisableForwarding yes
X11Forwarding no
PermitUserEnvironment no
PermitUserRC no
PrintMotd no
UseDNS no
LogLevel VERBOSE
Subsystem sftp internal-sftp
'''


def status():
    supported = installed()
    value = read() if supported else {'enabled': False, 'sources': []}
    active = run(['systemctl', 'is-active', UNIT], ok=(0, 3, 4)) if supported else 'unavailable'
    job = update.read(ROOT / 'install.json', {'status': 'idle'}) if supported else {'status': 'idle'}
    if supported and job.get('status') in {'queued', 'installing'} and time.time() - job.get('at', 0) > 30:
        if run(['systemctl', 'is-active', INSTALL_UNIT], ok=(0, 3, 4)) not in {'active', 'activating'}:
            job = {'status': 'failed', 'error': 'SSH component installation was interrupted. Review PC & driver updates before retrying.'}
            update.atomic(ROOT / 'install.json', job)
    fingerprint = None
    if supported and (ROOT / 'host_ed25519.pub').exists():
        fingerprint = run(['ssh-keygen', '-lf', str(ROOT / 'host_ed25519.pub')])
    return {'supported': supported, 'server_installed': supported and SSHD.exists(),
            'enabled': bool(value.get('enabled')), 'active': active == 'active',
            'sources': value.get('sources', []), 'port': PORT, 'username': USER,
            'fingerprint': fingerprint, 'install': job,
            'password_account': value.get('owner_username'),
            'password_sync_pending': bool(value.get('password_pending')),
            'reason': None if supported else 'SSH access runs on the installed AirLink Linux PC. It is unavailable in preview.'}


def action(name, payload):
    with LOCK:
        if name == 'status':
            return status()
        if not installed() or os.geteuid() != 0:
            raise ValueError('SSH access requires the installed AirLink Linux PC')
        ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
        if name in {'password.prepare', 'password.finish'}:
            value = read()
            if not value.get('enabled') or value.get('owner_id') != payload.get('owner_id') or not value.get('owner_id'):
                return {'prepared': False, 'synced': False}
            password = validate_password(payload.get('ssh_password'))
            if not managed_account():
                raise ValueError('The SSH account is missing; review SSH settings before changing the password')
            if name == 'password.prepare':
                token = secrets.token_hex(24)
                value['password_pending'] = token
                update.atomic(ROOT / 'settings.json', value)
                run(['usermod', '--lock', USER])
                return {'prepared': True, 'token': token}
            token = payload.get('token')
            if not isinstance(token, str) or not token or not value.get('password_pending') or not secrets.compare_digest(token, value['password_pending']):
                raise ValueError('SSH password synchronization changed; save SSH settings again')
            run(['chpasswd'], secret=USER + ':' + password + '\n')
            value.pop('password_pending', None)
            update.atomic(ROOT / 'settings.json', value)
            return {'synced': True}
        if name == 'install':
            if SSHD.exists():
                return status()
            with pc.maintenance_lock():
                pc.check_other_maintenance()
                state = pc.reconcile(locked=True)
                if state['status'] in pc.BUSY or state.get('recovery_required'):
                    raise ValueError('Finish or recover the PC update before installing the SSH component')
                if status()['install'].get('status') in {'queued', 'installing'}:
                    raise ValueError('SSH component installation is already running')
                update.atomic(ROOT / 'install.json', {'status': 'queued', 'at': time.time()})
                try:
                    run(['systemctl', 'start', '--no-block', INSTALL_UNIT])
                except Exception:
                    update.atomic(ROOT / 'install.json', {'status': 'failed', 'error': 'Could not queue SSH installation'})
                    raise
            return status()
        if name not in {'enable', 'disable'}:
            raise ValueError('Unknown SSH action')
        allowed = sources(payload.get('sources')) if name == 'enable' else None
        password = validate_password(payload.get('ssh_password')) if name == 'enable' else None
        if name == 'enable' and (not isinstance(payload.get('owner_id'), str) or not payload['owner_id'] or
                                 not isinstance(payload.get('owner_username'), str) or not payload['owner_username']):
            raise ValueError('A verified owner account is required for SSH')
        if name == 'enable' and not SSHD.exists():
            raise ValueError('Install the SSH server component first')
        # Enabling remote access does not change packages, and remains available
        # for failed-update recovery when OpenSSH is already installed.
        with pc.maintenance_lock():
            if update.restart_status()['pending']:
                raise ValueError('Wait for the pending restart before changing SSH access')
            managed_account()  # Detect unrelated accounts before making any changes.
            value = {'enabled': False, 'sources': read().get('sources', [])}
            update.atomic(ROOT / 'settings.json', value)
            try:
                stop()
            finally:
                firewall(value)
            if name == 'disable':
                return status()
            try:
                managed_account(create=True)
                if not (ROOT / 'host_ed25519').exists():
                    run(['ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', str(ROOT / 'host_ed25519')])
                Path('/run/sshd').mkdir(mode=0o755, exist_ok=True)
                write_file(CONFIG, configuration())
                run([str(SSHD), '-t', '-f', str(CONFIG)])
                write_file(SUDOERS, f'{USER} ALL=(ALL:ALL) ALL\n', 0o440)
                run(['visudo', '-cf', str(SUDOERS)])
                run(['chpasswd'], secret=USER + ':' + password + '\n')
                value = {'enabled': True, 'sources': allowed,
                         'owner_id': payload['owner_id'], 'owner_username': payload['owner_username']}
                update.atomic(ROOT / 'settings.json', value)
                firewall(value)
                run(['systemctl', 'enable', '--now', UNIT])
                if run(['systemctl', 'is-active', UNIT], ok=(0, 3, 4)) != 'active':
                    raise ValueError('SSH did not start; review the airlink-ssh service journal')
            except Exception:
                value['enabled'] = False
                update.atomic(ROOT / 'settings.json', value)
                try:
                    stop()
                finally:
                    firewall(value)
                raise
            return status()


def install_worker():
    """Optional component bootstrap for older appliances; never bypass recovery."""
    if not installed() or os.geteuid() != 0:
        raise ValueError('Installed Linux appliance required')
    ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
    changing = False
    with pc.maintenance_lock(blocking=True):
        try:
            pc.check_other_maintenance()
            state = pc.reconcile(locked=True)
            if state['status'] in pc.BUSY or state.get('recovery_required'):
                raise ValueError('Finish or recover the PC update before installing SSH')
            update.atomic(ROOT / 'install.json', {'status': 'installing', 'at': time.time()})
            if pc.run(['dpkg', '--audit']).strip():
                raise ValueError('Unfinished package configuration requires recovery first')
            if SSHD.exists():
                update.atomic(ROOT / 'install.json', {'status': 'installed'})
                return
            # The distro's default port-22 listener must never start at install.
            run(['systemctl', 'mask', 'ssh.service', 'ssh.socket'], timeout=90)
            pc.run(pc.APT + ['update'], timeout=900)
            command = pc.APT + ['--no-remove', '--assume-yes', 'install', 'openssh-server']
            pc.run(command + ['--download-only'], timeout=900)
            pc.run(['/bin/bash', '/opt/airlink/os/recovery/backup.sh'], timeout=600)
            changing = True
            pc.write_state('installing', operation='ssh_component')
            pc.run(command + ['--no-download'], timeout=900)
            if pc.run(['dpkg', '--audit']).strip() or not SSHD.exists():
                raise ValueError('SSH package installation needs local recovery review')
            pc.write_state('installed', operation='ssh_component')
            update.atomic(ROOT / 'install.json', {'status': 'installed'})
        except Exception as exc:
            if changing:
                pc.write_state('failed', recovery_required=True, error='SSH package installation failed. Review airlink-ssh-install.service.')
            update.atomic(ROOT / 'install.json', {'status': 'failed', 'error': str(exc)})
            raise


if __name__ == '__main__':
    if os.geteuid() != 0:
        raise SystemExit('Root required')
    if sys.argv[1:] == ['firewall']:
        firewall()
    elif sys.argv[1:] == ['install']:
        install_worker()
    else:
        raise SystemExit('Usage: remote_ssh.py firewall|install')
