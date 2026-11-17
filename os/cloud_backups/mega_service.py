"""Encrypted MEGA settings and persistent weekly backup scheduling."""
from contextlib import nullcontext
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import tempfile
import threading
from zoneinfo import ZoneInfo
from cryptography.fernet import Fernet

from . import mega
from . import service as cloud
from recovery.cloud_archive import transform

DEFAULTS = {'email': '', 'folder': 'AirLink Backups', 'automatic_enabled': False,
            'weekday': 6, 'time': '02:00', 'timezone': 'Europe/Zurich'}
ACTIVE = ('queued', 'creating', 'encrypting', 'uploading', 'verifying')


class MegaBackupService:
    def __init__(self, root=Path('/var/lib/airlink-system/mega-backup'), archive=None, enabled=True,
                 restore_validate=None, restore_apply=None):
        self.root = Path(root)
        self.archive = archive
        self.enabled = enabled
        self.lock = threading.RLock()
        self.running = False
        self.testing = False
        self.timer = None
        self.stopped = threading.Event()
        from .mega_restore import MegaRestore
        self.recovery = MegaRestore(self, restore_validate, restore_apply)

    def cipher(self):
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        path = self.root/'settings.key'
        if not path.exists():
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'wb') as output:
                output.write(Fernet.generate_key())
        return Fernet(path.read_bytes())

    def config(self):
        path = self.root/'settings.enc'
        return {**DEFAULTS, **(json.loads(self.cipher().decrypt(path.read_bytes())) if path.exists() else {})}

    def save_config(self, config):
        cloud.atomic(self.root/'settings.enc', self.cipher().encrypt(json.dumps(config).encode()))

    def state(self):
        return cloud.load_json(self.root/'status.json')

    def progress(self, **changes):
        with self.lock:
            current = self.state()
            current.update(changes)
            cloud.atomic(self.root/'status.json', json.dumps(current).encode())

    def status(self):
        with self.lock:
            config = self.config()
            return {**{key: config[key] for key in DEFAULTS},
                    'connected': bool(config.get('verified')),
                    'has_account_password': bool(config.get('account_password')),
                    'has_backup_password': bool(config.get('backup_password')),
                    'supported': bool(mega.binary()) and self.enabled and
                        (self.archive is not None or Path(cloud.BACKUP_SCRIPT).exists()),
                    'transfer_available': bool(mega.binary()), 'local_mode': self.archive is not None,
                    'running': self.running, 'testing': self.testing, 'state': self.state(),
                    'restore': self.recovery.public()}

    def idle(self):
        if self.running or self.testing or self.recovery.state().get('status') in {'uploading', 'awaiting_restart'}:
            raise ValueError('Wait for the backup, upload, recovery or connection test to finish before changing settings.')

    def configure(self, data):
        with self.lock:
            self.idle()
            config = self.config()
            email = str(data.get('email', '')).strip()
            if len(email) > 254 or not re.fullmatch(r'[A-Za-z0-9.!#$%&\x27*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}', email):
                raise ValueError('Enter your MEGA account email')
            folder = str(data.get('folder', '')).strip()
            if (not 1 <= len(folder) <= 200 or not re.fullmatch(r'[A-Za-z0-9 _./-]+', folder)
                    or any(part in ('', '.', '..') or part != part.strip() for part in folder.split('/'))):
                raise ValueError('Use a relative MEGA folder path with letters, numbers, spaces, dots, hyphens or underscores')
            if type(data.get('automatic_enabled')) is not bool or type(data.get('weekday')) is not int or not 0 <= data['weekday'] <= 6:
                raise ValueError('Select a weekly backup day')
            if not re.fullmatch(r'(?:[01][0-9]|2[0-3]):[0-5][0-9]', str(data.get('time', ''))):
                raise ValueError('Enter the backup time as HH:MM')
            try:
                ZoneInfo(str(data.get('timezone', '')))
            except (ValueError, KeyError):
                raise ValueError('Enter an IANA timezone, such as Europe/Zurich or Asia/Baghdad') from None
            password = data.get('account_password') or config.get('account_password')
            encryption = data.get('backup_password') or config.get('backup_password')
            if not isinstance(password, str) or not 1 <= len(password) <= 1024 or any(c in password for c in '\r\n\x00'):
                raise ValueError('Enter your MEGA account password without line breaks')
            if not isinstance(encryption, str) or not 12 <= len(encryption) <= 1024:
                raise ValueError('Use a backup encryption password with 12–1024 characters')
            if email != config['email'] and not data.get('account_password'):
                raise ValueError('Enter the password for the new MEGA account')
            if (email, password, folder) != (config['email'], config.get('account_password'), config['folder']):
                config['verified'] = False
            previous_schedule = tuple(config[key] for key in ('automatic_enabled', 'weekday', 'time', 'timezone'))
            config.update({key: data[key] for key in ('automatic_enabled', 'weekday', 'time', 'timezone')})
            config.update(email=email, folder=folder, account_password=password, backup_password=encryption)
            self.save_config(config)
            if not config['automatic_enabled'] or not config.get('verified'):
                self.progress(next_run_at=None)
            elif previous_schedule != tuple(config[key] for key in ('automatic_enabled', 'weekday', 'time', 'timezone')) or not self.state().get('next_run_at'):
                self.progress(next_run_at=cloud.next_run(config))
            return self.status()

    def test_connection(self):
        with self.lock:
            self.idle()
            config = self.config()
            if not config.get('account_password'):
                raise ValueError('Save your MEGA settings first')
            self.testing = True
        try:
            mega.check_connection(config, self.root)
            with self.lock:
                config['verified'] = True
                self.save_config(config)
                self.progress(connection_error=None, connection_checked_at=cloud.stamp(),
                    next_run_at=(self.state().get('next_run_at') or cloud.next_run(config)) if config['automatic_enabled'] else None)
        except Exception:
            with self.lock:
                config['verified'] = False
                self.save_config(config)
                self.progress(next_run_at=None, connection_error='MEGA connection failed. Check your login and account access.')
            raise
        finally:
            with self.lock:
                self.testing = False
        return self.status()

    def disconnect(self):
        with self.lock:
            self.idle()
            config = self.config()
            config.pop('account_password', None)
            config.update(verified=False, automatic_enabled=False)
            self.save_config(config)
            self.progress(next_run_at=None, connection_error=None)
            return self.status()

    def queue(self, scheduled=False):
        with self.lock:
            self.idle()
            config = self.config()
            if not config.get('verified') or not config.get('account_password') or not config.get('backup_password'):
                raise ValueError('Save your settings and successfully test the MEGA connection first')
            if not self.status()['supported']:
                raise ValueError('MEGA backups require transfer support and a running live server')
            changes = dict(status='queued', started_at=cloud.stamp(), finished_at=None, error=None, total_bytes=None)
            if scheduled:
                changes['next_run_at'] = cloud.next_run(config)
            self.progress(**changes)
            self.running = True
            try:
                threading.Thread(target=self.run_backup, args=(config,), name='mega-backup', daemon=True).start()
            except Exception:
                self.running = False
                self.progress(status='failed', finished_at=cloud.stamp(), error='Cannot start the MEGA backup worker. Try again.')
                raise ValueError('Cannot start the MEGA backup worker. Try again.') from None
            return self.status()

    def run_backup(self, config):
        try:
            self.progress(status='creating')
            with tempfile.TemporaryDirectory(prefix='work-', dir=self.root) as temporary:
                work = Path(temporary)
                # Release appliance maintenance after creating the consistent archive.
                with (cloud.maintenance() if self.archive is None else nullcontext()):
                    (self.archive or cloud.archive)(work/'backup.tar')
                self.progress(status='encrypting')
                upload = work/'upload'; upload.mkdir(mode=0o700)
                encrypted = upload/('AirLink-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+secrets.token_hex(4)+'.tar.airlink')
                transform(work/'backup.tar', encrypted, config['backup_password'])
                (work/'backup.tar').unlink()
                result = mega.upload(config, encrypted, self.root, self.progress)
                self.progress(status='completed', finished_at=cloud.stamp(), last_success_at=cloud.stamp(), last_backup=result, error=None)
        except Exception:
            self.progress(status='failed', finished_at=cloud.stamp(),
                          error='MEGA backup failed. Check account access, storage/transfer quota, network and local maintenance. Retry with Back up now.')
        finally:
            with self.lock:
                try:
                    current = self.state()
                    entry = {key: current.get(key) for key in ('status', 'started_at', 'finished_at', 'error')}
                    if current.get('status') == 'completed':
                        entry['backup'] = current['last_backup']
                    self.progress(history=[entry, *current.get('history', [])][:20])
                finally:
                    self.running = False

    def tick(self):
        with self.lock:
            self.recovery.public()  # Expire and remove unconfirmed plaintext recovery files.
            config, current = self.config(), self.state()
            if (self.running or self.testing or self.recovery.state().get('status') in {'uploading', 'awaiting_restart'}
                    or not self.enabled or not config['automatic_enabled'] or not config.get('verified')):
                return
            due = current.get('next_run_at')
            if not due:
                self.progress(next_run_at=cloud.next_run(config))
            elif datetime.fromisoformat(due) <= datetime.now(timezone.utc):
                self.queue(scheduled=True)

    def start(self):
        if self.timer and self.timer.is_alive():
            return
        with self.lock:
            self.recovery.startup()
            if self.state().get('status') in ACTIVE:
                self.progress(status='failed', finished_at=cloud.stamp(), error='MEGA backup interrupted by restart. Retry with Back up now.')
            # Private temporary archives/configs from an interrupted process are no longer needed.
            if self.root.exists():
                for pattern in ('work-*', 'connection-*'):
                    for path in self.root.glob(pattern):
                        if path.is_dir() and not path.is_symlink():
                            shutil.rmtree(path)
        self.stopped.clear()
        def watch():
            while not self.stopped.is_set():
                try:
                    self.tick()
                except Exception:
                    self.progress(error='Weekly MEGA backup could not start. Check transfer support and settings.')
                self.stopped.wait(60)
        self.timer = threading.Thread(target=watch, name='weekly-mega-backup', daemon=True)
        self.timer.start()

    def stop(self):
        self.stopped.set()
        if self.timer:
            self.timer.join(timeout=2)

    def action(self, name, data):
        if name == 'restore.upload.start': return self.recovery.upload_start(data)
        if name == 'restore.upload.chunk': return self.recovery.upload_chunk(data)
        if name == 'restore.upload.prepare': return self.recovery.upload_prepare(data)
        if name == 'files': return self.recovery.files()
        if name == 'restore.prepare': return self.recovery.prepare(data)
        if name == 'restore.confirm': return self.recovery.confirm(data)
        if name == 'restore.cancel': return self.recovery.cancel(data)
        if name == 'restore.status':
            with self.lock:
                return self.recovery.public(data['owner_id'])
        if name == 'status': return self.status()
        if name == 'configure': return self.configure(data)
        if name == 'test': return self.test_connection()
        if name == 'disconnect': return self.disconnect()
        if name == 'run': return self.queue()
        raise ValueError('Unknown MEGA backup action')


service = MegaBackupService()
