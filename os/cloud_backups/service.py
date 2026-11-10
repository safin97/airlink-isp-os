"""Root-owned Google Drive backup settings and weekly background jobs."""
import base64
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import fcntl
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import subprocess
import tarfile
import tempfile
import threading
import time
import urllib.parse
from zoneinfo import ZoneInfo
from cryptography.fernet import Fernet
from . import google_drive as drive
from recovery.cloud_archive import transform
from updates import update

ROOT = Path('/var/lib/airlink-system/google-drive-backup')
BACKUPS = Path('/var/backups/airlink')
BACKUP_SCRIPT = '/opt/airlink/os/recovery/backup.sh'
CALLBACK = '/api/backups/google-drive/callback'
UTC = timezone.utc
DEFAULTS = {'client_id': '', 'redirect_uri': '', 'folder_name': 'AirLink Backups',
            'automatic_enabled': False, 'weekday': 6, 'time': '02:00', 'timezone': 'UTC'}


def stamp():
    return datetime.now(UTC).isoformat()


def next_run(config, clock=None):
    clock = clock or datetime.now(UTC)
    zone = ZoneInfo(config['timezone'])
    local = clock.astimezone(zone)
    hour, minute = map(int, config['time'].split(':'))
    target = (local + timedelta(days=(config['weekday']-local.weekday()) % 7)).replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= local:
        target += timedelta(days=7)
    return target.astimezone(UTC).isoformat()


def redirect_uri(value):
    try:
        parsed = urllib.parse.urlsplit(value)
        parsed.port  # Reject malformed ports before storing the callback.
    except ValueError:
        raise ValueError('Enter a valid Google callback URL') from None
    local = parsed.hostname == 'localhost'
    try:
        ip = ipaddress.ip_address(parsed.hostname or '')
    except ValueError:
        ip = None
    if ip is not None:
        local = ip.is_loopback
        if not local:
            raise ValueError('Google sign-in needs an HTTPS domain, not a public IP address')
    if (not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.path != CALLBACK or parsed.scheme not in (('http', 'https') if local else ('https',))):
        raise ValueError('Enter the HTTPS Google callback URL shown in the setup instructions')
    if not local and ('.' not in parsed.hostname or not all(
            re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', label)
            for label in parsed.hostname.split('.'))):
        raise ValueError('Google sign-in needs a valid HTTPS domain')
    return value


def atomic(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix='.backup-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as output:
            output.write(value)
            output.flush(); os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def load_json(path):
    return json.loads(path.read_text()) if path.exists() else {}


def cipher():
    ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
    path = ROOT/'settings.key'
    if not path.exists():
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, 'wb') as output:
            output.write(Fernet.generate_key())
    return Fernet(path.read_bytes())


def configuration():
    path = ROOT/'settings.enc'
    return {**DEFAULTS, **(json.loads(cipher().decrypt(path.read_bytes())) if path.exists() else {})}


def save_config(config):
    atomic(ROOT/'settings.enc', cipher().encrypt(json.dumps(config).encode()))


def state():
    return load_json(ROOT/'status.json')


def save_state(data):
    atomic(ROOT/'status.json', json.dumps(data).encode())


@contextmanager
def maintenance():
    update.ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
    with (update.ROOT/'lock').open('w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('An update or maintenance operation is running. Retry the backup later.') from None
        if update.read(update.ROOT/'state.json', {}).get('status') in ('queued', 'installing') or update.restart_status()['pending']:
            raise ValueError('An update or restart is pending. Retry the backup after it finishes.')
        yield


def archive(destination):
    result = subprocess.run(['bash', BACKUP_SCRIPT], capture_output=True, text=True, timeout=600)
    if result.returncode:
        raise ValueError('Local backup creation failed. Review the local backup service logs.')
    source = Path(result.stdout.strip())
    if source.is_symlink() or source.parent.resolve() != BACKUPS.resolve() or not source.is_dir():
        raise ValueError('The local backup service returned an invalid directory')
    names = ('database.dump', 'configuration.tar.gz', 'SHA256SUMS')
    for name in names:
        if not (source/name).is_file() or (source/name).is_symlink():
            raise ValueError('The local backup is incomplete')
    expected = {}
    for line in (source/'SHA256SUMS').read_text().splitlines():
        digest, name = line.split()
        expected[name] = digest
    for name in names[:2]:
        digest = hashlib.sha256()
        with (source/name).open('rb') as file:
            for block in iter(lambda: file.read(1024 * 1024), b''):
                digest.update(block)
        if expected.get(name) != digest.hexdigest():
            raise ValueError('Local backup checksum verification failed')
    with tarfile.open(destination, 'w') as bundle:
        for name in names:
            bundle.add(source/name, arcname=name, recursive=False)
    return source.name


class BackupService:
    def __init__(self):
        self.lock = threading.RLock()
        self.running = False
        self.timer = None
        self.stopped = threading.Event()

    def status(self):
        with self.lock:
            config, current = configuration(), state()
            return {**{key: config[key] for key in DEFAULTS},
                'has_client_secret': bool(config.get('client_secret')),
                'has_backup_password': bool(config.get('backup_password')),
                'connected': bool(config.get('refresh_token')), 'account_email': config.get('account_email', ''),
                'folder_url': 'https://drive.google.com/drive/folders/'+config['folder_id'] if config.get('folder_id') else None,
                'running': self.running, 'state': current,
                'supported': Path(BACKUP_SCRIPT).exists()}

    def idle(self):
        if self.running:
            raise ValueError('A backup is running. Wait for it to finish before changing settings.')

    def configure(self, data):
        with self.lock:
            self.idle()
            config = configuration()
            if not re.fullmatch(r'[A-Za-z0-9._-]{10,250}\.apps\.googleusercontent\.com', data.get('client_id', '')):
                raise ValueError('Enter a Google OAuth client ID')
            uri = redirect_uri(str(data.get('redirect_uri', '')))
            folder_name = str(data.get('folder_name', 'AirLink Backups')).strip()
            if not folder_name or len(folder_name) > 100 or any(ord(c) < 32 for c in folder_name):
                raise ValueError('Enter a backup folder name with 1–100 characters')
            if type(data.get('automatic_enabled')) is not bool or type(data.get('weekday')) is not int or not 0 <= data['weekday'] <= 6:
                raise ValueError('Select the weekly backup day')
            if not re.fullmatch(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]', str(data.get('time', ''))):
                raise ValueError('Enter the backup time as HH:MM')
            zone = str(data.get('timezone', ''))
            try:
                ZoneInfo(zone)
            except (ValueError, KeyError):
                raise ValueError('Enter an IANA timezone, such as Europe/Zurich or Asia/Baghdad') from None
            client_secret = data.get('client_secret') or config.get('client_secret')
            password = data.get('backup_password') or config.get('backup_password')
            if not isinstance(client_secret, str) or not 8 <= len(client_secret) <= 4096:
                raise ValueError('Enter the OAuth client secret')
            if not isinstance(password, str) or not 12 <= len(password) <= 1024:
                raise ValueError('Use a backup encryption password with at least 12 characters')
            if data['client_id'] != config['client_id'] and not data.get('client_secret'):
                raise ValueError('Enter the secret for the new OAuth client')
            if any((data['client_id'] != config['client_id'], uri != config['redirect_uri'],
                    client_secret != config.get('client_secret'))):
                for key in ('refresh_token', 'account_email', 'folder_id', 'pending'):
                    config.pop(key, None)
            if folder_name != config['folder_name']:
                config.pop('folder_id', None)
            config.update({key: data[key] for key in ('client_id', 'automatic_enabled', 'weekday', 'time', 'timezone')})
            config.update(client_secret=client_secret, backup_password=password, redirect_uri=uri, folder_name=folder_name)
            save_config(config)
            current = state()
            current['next_run_at'] = next_run(config) if config['automatic_enabled'] else None
            save_state(current)
            return self.status()

    def authorize(self, owner_id, callback):
        with self.lock:
            self.idle()
            config = configuration()
            if not config.get('client_secret'):
                raise ValueError('Save your Google OAuth settings first')
            if callback != config['redirect_uri']:
                raise ValueError('Open AirLink using the HTTPS domain configured in the callback URL, then connect again')
            nonce, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(48)
            config['pending'] = {'state': hashlib.sha256(nonce.encode()).hexdigest(), 'verifier': verifier,
                                 'expires': time.time()+600, 'owner_id': owner_id}
            save_config(config)
            challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
            return {'state': nonce, 'authorization_url': 'https://accounts.google.com/o/oauth2/v2/auth?' + urllib.parse.urlencode({
                'client_id': config['client_id'], 'redirect_uri': callback, 'response_type': 'code', 'scope': drive.SCOPE,
                'access_type': 'offline', 'prompt': 'consent', 'state': nonce, 'code_challenge': challenge, 'code_challenge_method': 'S256'})}

    def complete(self, owner_id, nonce, code):
        with self.lock:
            self.idle()
            config = configuration()
            pending = config.get('pending', {})
            if (pending.get('owner_id') != owner_id or pending.get('expires', 0) < time.time() or
                    not secrets.compare_digest(pending.get('state', ''), hashlib.sha256(nonce.encode()).hexdigest())):
                raise ValueError('Google sign-in expired or did not match this owner. Connect again.')
            config.pop('pending', None); save_config(config)
            tokens = drive.token(config, code=code, verifier=pending['verifier'])
            if not tokens.get('refresh_token') or (tokens.get('scope') and drive.SCOPE not in tokens['scope'].split()):
                raise ValueError('Google did not grant offline Drive access. Connect again and allow backup access.')
            email = drive.account(tokens['access_token'])
            folder_id = drive.folder(tokens['access_token'], config['folder_name'])
            config.update(refresh_token=tokens['refresh_token'], account_email=email, folder_id=folder_id)
            save_config(config)
            return self.status()

    def disconnect(self):
        with self.lock:
            self.idle()
            config = configuration()
            token = config.get('refresh_token')
            for key in ('refresh_token', 'account_email', 'folder_id', 'pending'):
                config.pop(key, None)
            config['automatic_enabled'] = False
            save_config(config)
            current = state(); current['next_run_at'] = None; save_state(current)
            result = self.status()
            if token:
                try:
                    status, _, _ = drive.request('POST', 'https://oauth2.googleapis.com/revoke', form={'token': token})
                    if status != 200:
                        raise drive.DriveError('Revocation failed')
                except drive.DriveError:
                    result['notice'] = 'Disconnected locally. You can also remove AirLink access from your Google Account.'
            return result

    def queue(self, scheduled=False):
        with self.lock:
            self.idle()
            config = configuration()
            if not config.get('refresh_token') or not config.get('backup_password'):
                raise ValueError('Save an encryption password and connect Google Drive first')
            if not Path(BACKUP_SCRIPT).exists():
                raise ValueError('Backup creation is available on the installed AirLink appliance')
            current = state()
            current.update(status='queued', started_at=stamp(), finished_at=None, error=None, uploaded_bytes=0, total_bytes=None)
            if scheduled:
                current['next_run_at'] = next_run(config)
            save_state(current)
            self.running = True
            try:
                threading.Thread(target=self.run_backup, args=(config,), name='google-drive-backup', daemon=True).start()
            except Exception:
                self.running = False
                current.update(status='failed', error='Cannot start the backup worker. Retry the backup.', finished_at=stamp())
                save_state(current)
                raise ValueError(current['error']) from None
            return self.status()

    def progress(self, **changes):
        with self.lock:
            current = state(); current.update(changes); save_state(current)

    def run_backup(self, config):
        try:
            with maintenance():
                self.progress(status='creating')
                ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
                with tempfile.TemporaryDirectory(prefix='work-', dir=ROOT) as work:
                    work = Path(work)
                    local_name = archive(work/'backup.tar')
                    encrypted = work/('AirLink-'+datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')+'-'+secrets.token_hex(4)+'.tar.airlink')
                    self.progress(status='encrypting', local_backup=local_name)
                    transform(work/'backup.tar', encrypted, config['backup_password'])
                    tokens = drive.token(config)
                    folder_id = drive.folder(tokens['access_token'], config['folder_name'], config.get('folder_id'))
                    config['folder_id'] = folder_id
                    with self.lock:
                        save_config(config)
                    self.progress(status='uploading')
                    uploaded = drive.upload(tokens['access_token'], folder_id, encrypted,
                        lambda sent, total: self.progress(uploaded_bytes=sent, total_bytes=total))
                    self.progress(status='completed', finished_at=stamp(), last_success_at=stamp(), last_backup=uploaded, error=None)
        except (drive.DriveError, ValueError) as exc:
            self.progress(status='failed', finished_at=stamp(), error=str(exc))
        except Exception:
            self.progress(status='failed', finished_at=stamp(), error='Backup failed. Check local backup services, free disk space and Google connection settings.')
        finally:
            with self.lock:
                try:
                    current = state()
                    history = current.get('history', [])
                    history.insert(0, {key: current.get(key) for key in ('status', 'started_at', 'finished_at', 'error')} |
                        ({'backup': current['last_backup']} if current.get('status') == 'completed' else {}))
                    current['history'] = history[:20]
                    save_state(current)
                finally:
                    self.running = False

    def tick(self):
        with self.lock:
            config, current = configuration(), state()
            if self.running or not config['automatic_enabled'] or not config.get('refresh_token'):
                return
            due = current.get('next_run_at')
            if not due:
                current['next_run_at'] = next_run(config); save_state(current)
            elif datetime.fromisoformat(due) <= datetime.now(UTC):
                self.queue(scheduled=True)

    def start(self):
        if self.timer and self.timer.is_alive():
            return
        with self.lock:
            current = state()
            if current.get('status') in ('queued', 'creating', 'encrypting', 'uploading'):
                current.update(status='failed', error='The backup was interrupted by a server restart. Start a new backup.', finished_at=stamp())
                save_state(current)
        self.stopped.clear()
        def watch():
            while not self.stopped.is_set():
                try:
                    self.tick()
                except Exception:
                    pass  # Keep the controller available; failures never expose credentials in logs.
                self.stopped.wait(60)
        self.timer = threading.Thread(target=watch, name='weekly-drive-backup', daemon=True)
        self.timer.start()

    def stop(self):
        self.stopped.set()
        if self.timer:
            self.timer.join(timeout=2)

    def action(self, name, data):
        if name == 'status': return self.status()
        if name == 'configure': return self.configure(data)
        if name == 'authorize': return self.authorize(data['owner_id'], data['callback'])
        if name == 'complete': return self.complete(data['owner_id'], data['state'], data['code'])
        if name == 'disconnect': return self.disconnect()
        if name == 'run': return self.queue()
        raise ValueError('Unknown Google Drive backup action')


service = BackupService()
