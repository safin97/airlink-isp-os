"""Local panel operations. Never exposed as a remote command endpoint."""
import fcntl
import ipaddress
import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from updates import update

BASE = 'http://127.0.0.1:8000/api'
BACKUPS = Path('/var/backups/airlink')
ZONEINFO = Path('/usr/share/zoneinfo')


class SessionExpired(ValueError):
    pass


def api(method, path, token='', data=None):
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    req = urllib.request.Request(BASE + path, method=method, headers=headers,
                                 data=json.dumps(data).encode() if data is not None else None)
    try:
        with urllib.request.urlopen(req, timeout=180) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403) and token:
            raise SessionExpired('Your owner session ended. Sign in again.') from None
        try:
            detail = json.load(exc).get('detail', 'Request failed')
            if isinstance(detail, list):
                detail = '; '.join(str(item.get('msg', 'Invalid value')) for item in detail)
        except (ValueError, AttributeError):
            detail = 'Request failed (' + str(exc.code) + ')'
        raise ValueError(str(detail)) from None


def run(args, timeout=30, **options):
    result = subprocess.run(args, capture_output=True, text=True, timeout=timeout, **options)
    if result.returncode:
        raise ValueError((result.stderr or result.stdout or 'System command failed').strip())
    return result.stdout.strip()


def network_payload(interface, method, address, subnet, gateway, dns, hostname):
    from network.configure import validate
    payload = {'interface': interface, 'method': method, 'hostname': hostname.strip()}
    if method == 'static':
        try:
            prefix = ipaddress.IPv4Network('0.0.0.0/' + subnet.strip().lstrip('/')).prefixlen
        except ValueError:
            raise ValueError('Subnet must be a prefix such as 24 or a mask such as 255.255.255.0') from None
        payload.update(address=address.strip(), prefix=prefix, gateway=gateway.strip(),
                       dns=[part for part in re.split(r'[,\s]+', dns.strip()) if part])
    return validate(payload)


def timezones():
    return run(['timedatectl', 'list-timezones']).splitlines()


def settings_status():
    props = dict(line.split('=', 1) for line in run(['timedatectl', 'show']).splitlines() if '=' in line)
    return {'hostname': run(['hostnamectl', '--static']), 'timezone': props.get('Timezone', 'UTC'),
            'ntp': props.get('NTP') == 'yes', 'can_ntp': props.get('CanNTP') == 'yes',
            'synchronized': props.get('NTPSynchronized') == 'yes',
            'local_time': run(['date', '--iso-8601=seconds']), 'timezones': timezones()}


def validate_settings(data):
    hostname = str(data.get('hostname', ''))
    if not re.fullmatch(r'[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?', hostname):
        raise ValueError('Use a hostname with 1–63 letters, digits or hyphens, without spaces')
    zone = str(data.get('timezone', ''))
    if zone not in timezones():
        raise ValueError('Select a valid timezone')
    if type(data.get('ntp')) is not bool:
        raise ValueError('Choose automatic or manual time')
    manual = data.get('manual_time', '')
    if manual:
        if data['ntp']:
            raise ValueError('Turn off automatic time before setting the clock manually')
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}', manual):
            raise ValueError('Enter local date/time as YYYY-MM-DD HH:MM:SS')
        datetime.strptime(manual, '%Y-%m-%d %H:%M:%S')
    return hostname, zone, data['ntp'], manual


def backup_paths():
    return sorted(p.name for p in BACKUPS.glob('*') if p.is_dir() and not p.is_symlink()
                  and (p / 'SHA256SUMS').is_file())


def local_action(name, data, token):
    # Check the live API session and owner role before EVERY privileged operation.
    user = api('GET', '/auth/me', token)
    if user.get('role') != 'owner':
        raise SessionExpired('Owner access is required')
    if name == 'settings':
        return settings_status()
    if name == 'logs':
        return run(['journalctl', '--no-pager', '-n', '100', '-u', 'airlink-api', '-u', 'airlink-monitor',
                    '-u', 'airlink-controller', '-u', 'airlink-console', '-u', 'airlink-update-job'])
    if name == 'backups':
        return backup_paths()
    if name not in {'save_settings', 'backup', 'restore', 'restart_services', 'shutdown'}:
        raise ValueError('Unknown local operation')
    if data.get('confirm') is not True:
        raise ValueError('Confirm the operation first')
    if name == 'shutdown':
        return update.restart_system({'confirm': True}, poweroff=True)
    update.ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (update.ROOT / 'lock').open('w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('An update or maintenance operation is running. Try again later.') from None
        if update.read(update.ROOT / 'state.json', {}).get('status') in {'queued', 'installing', 'failed'} or update.restart_status()['pending']:
            raise ValueError('An update or restart requires attention before changing system settings')
        if name == 'save_settings':
            from network import configure
            if configure.PENDING.exists() and json.loads(configure.PENDING.read_text()).get('deadline', 0) > time.time():
                raise ValueError('Keep or revert the pending network change before editing hostname or time')
            hostname, zone, ntp, manual = validate_settings(data)
            current = settings_status()
            if ntp and not current['can_ntp']:
                raise ValueError('No automatic time service is installed on this appliance')
            if current['can_ntp']:
                run(['timedatectl', 'set-ntp', 'true' if ntp else 'false'])
            run(['timedatectl', 'set-timezone', zone])
            if manual:
                run(['timedatectl', 'set-time', manual])
            run(['hostnamectl', 'set-hostname', hostname])
            # Keep the network form from reverting the hostname on its next confirmation.
            if configure.STATE.exists():
                saved = json.loads(configure.STATE.read_text())
                saved['hostname'] = hostname
                configure.write(configure.STATE, saved)
            result = 'Hostname and date/time settings saved. Sign in again if the clock change ends your session.'
        elif name == 'backup':
            result = run(['bash', '/opt/airlink/os/recovery/backup.sh'], timeout=600)
        elif name == 'restore':
            selected = data.get('backup')
            if selected not in backup_paths():
                raise ValueError('Select an existing local backup')
            result = run(['bash', '/opt/airlink/os/recovery/restore.sh', str(BACKUPS / selected), 'RESTORE'], timeout=600,
                         pass_fds=(lock.fileno(),), env={**os.environ, 'AIRLINK_MAINTENANCE_FD': str(lock.fileno())})
            result += '\nDatabase restored. Sign in again. Configuration archives require manual recovery review.'
        else:
            run(['systemctl', 'restart', 'airlink-api', 'airlink-monitor', 'airlink-alerts', 'nginx'], timeout=120)
            result = 'Services restarted.'
        run(['logger', '-t', 'airlink-panel', '--', 'Owner ' + str(user.get('id')) + ': ' + name])
        return result
