"""Download and verify first; replace data only after owner confirmation."""
from datetime import datetime, timedelta, timezone
import base64
import json
from pathlib import Path
import secrets
import re
import shutil
import subprocess
import tarfile
import threading

from . import mega, service as cloud
from recovery.cloud_archive import transform
from recovery.verified_archive import extract, MAX_ARCHIVE_BYTES

BUSY = {'downloading', 'checking', 'restoring', 'awaiting_restart'}


def appliance_validate(directory):
    # Network configuration is deliberately not restored by the web workflow.
    # Refuse a database whose encrypted credentials need a different key.
    def key(text):
        for line in text.splitlines():
            if line.startswith('AIRLINK_ENCRYPTION_KEY='):
                return line.split('=', 1)[1].strip().strip('\"\'')
        return None
    with tarfile.open(directory/'configuration.tar.gz', 'r:gz') as bundle:
        members, total, count = [], 0, 0
        for member in bundle:
            total += member.size
            count += 1
            if total > 512 * 1024 ** 2 or count > 4096:
                raise ValueError('Configuration archive is too large for online recovery')
            if member.name == 'etc/airlink/airlink.env':
                members.append(member)
        if len(members) != 1 or not members[0].isfile() or members[0].size > 65536:
            raise ValueError('Backup is missing its recovery key')
        saved = key(bundle.extractfile(members[0]).read().decode())
    current = key(Path('/etc/airlink/airlink.env').read_text())
    if not saved or saved != current:
        raise ValueError('This backup uses a different encryption key. Restore it through the local recovery console with its matching configuration.')
    result = subprocess.run(['pg_restore', '--list', str(directory/'database.dump')],
                            capture_output=True, timeout=60)
    if result.returncode:
        raise ValueError('Invalid or unsupported PostgreSQL backup')


def appliance_restore(directory):
    backups = Path('/var/backups/airlink')
    backups.mkdir(mode=0o700, parents=True, exist_ok=True)
    target = backups/('mega-' + secrets.token_hex(12))
    shutil.copytree(directory, target)
    # The script owns the maintenance lock, stops writers, and saves a safety backup.
    log = target/'recovery.log'
    with log.open('xb') as output:
        log.chmod(0o600)
        result = subprocess.run(['bash', '/opt/airlink/os/recovery/restore.sh', str(target), 'RESTORE'],
                                stdout=output, stderr=subprocess.STDOUT)
    if result.returncode:
        raise ValueError('Recovery did not finish. Review recovery service logs and the safety backup from the local console.')
    return {'status': 'completed', 'message': 'Database restored. Sign in again using an account from the backup.'}


class MegaRestore:
    def __init__(self, parent, validate=None, restore=None):
        self.parent = parent
        self.validate = validate or appliance_validate
        self.restore = restore or appliance_restore
        self.work = parent.root/'restore-prepared'

    def state(self):
        return cloud.load_json(self.parent.root/'restore.json')

    def progress(self, **changes):
        with self.parent.lock:
            state = self.state()
            state.update(changes)
            cloud.atomic(self.parent.root/'restore.json', json.dumps(state).encode())

    def public(self, owner_id=None):
        state = self.state()
        if state.get('status') in {'ready', 'uploading'} and datetime.fromisoformat(state['expires_at']) <= datetime.now(timezone.utc):
            self.clear()
            self.progress(status='expired', message='Prepared recovery expired. Select and verify the backup again.')
            state = self.state()
        return {k: v for k, v in state.items() if k != 'owner_id' and (k != 'token' or state.get('owner_id') == owner_id)}

    def clear(self):
        if self.work.exists():
            shutil.rmtree(self.work)

    def available(self):
        self.parent.idle()
        config = self.parent.config()
        if not self.parent.enabled or not mega.binary() or not config.get('verified') or not config.get('account_password'):
            raise ValueError('Save and test your MEGA connection on the live server first')
        if self.parent.archive is not None and self.restore == appliance_restore:
            raise ValueError('Local recovery is not configured')
        return config

    def files(self):
        with self.parent.lock:
            config = self.available()
            self.parent.testing = True
        try:
            return {'files': mega.list_backups(config, self.parent.root)}
        finally:
            with self.parent.lock:
                self.parent.testing = False

    def launch(self, target, args):
        self.parent.running = True
        try:
            threading.Thread(target=target, args=args, name='mega-restore', daemon=True).start()
        except Exception:
            self.parent.running = False
            self.progress(status='failed', error='Could not start recovery. Try again.')
            raise ValueError('Could not start recovery. Try again.') from None

    def prepare(self, data):
        with self.parent.lock:
            config = self.available()
            self.check_prepared_owner(data['owner_id'])
            name, password = data.get('filename'), data.get('password')
            if not mega.backup_name(name) or not isinstance(password, str) or not 12 <= len(password) <= 1024:
                raise ValueError('Select a backup and enter its encryption password')
            self.clear()
            self.work.mkdir(mode=0o700)
            cloud.atomic(self.parent.root/'restore.json', json.dumps({
                'status': 'downloading', 'source': 'mega', 'filename': name, 'owner_id': data['owner_id'],
                'token': secrets.token_hex(24), 'started_at': cloud.stamp(),
                'local_mode': self.parent.archive is not None,
            }).encode())
            self.launch(self.prepare_worker, (config, name, password))
            return self.public(data['owner_id'])

    def prepare_worker(self, config, name, password):
        try:
            # Listing rejects ambiguous duplicate names and files outside our backup folder.
            selected = next((row for row in mega.list_backups(config, self.parent.root) if row['filename'] == name), None)
            if selected is None:
                raise ValueError('Selected backup is no longer in the MEGA folder')
            size = selected.get('size')
            if not isinstance(size, int) or not 0 < size <= MAX_ARCHIVE_BYTES:
                raise ValueError('Backup size is unsupported for online recovery (maximum 20 GiB)')
            if shutil.disk_usage(self.work).free < size * 4:
                raise ValueError('Not enough free disk space to prepare and restore this backup')
            mega.time.sleep(3)
            mega.download(config, name, self.work/'encrypted', self.parent.root)
            self.verify(password, release=False)
        except ValueError as exc:
            self.clear()
            self.progress(status='failed', error=str(exc))
        except Exception:
            self.clear()
            self.progress(status='failed', error='Could not download the backup. Check connection, transfer quota and free disk space.')
        finally:
            with self.parent.lock:
                self.parent.running = False

    def verify(self, password, release=True):
        try:
            self.progress(status='checking')
            try:
                transform(self.work/'encrypted', self.work/'archive.tar', password, decrypt=True)
            except Exception:
                raise ValueError('Backup password is incorrect or the encrypted file is damaged') from None
            extract(self.work/'archive.tar', self.work/'data', self.parent.archive is not None)
            self.validate(self.work/'data')
            (self.work/'archive.tar').unlink()
            (self.work/'encrypted').unlink()
            self.progress(status='ready', expires_at=(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat(),
                          message='Backup verified. Confirmation is required before replacing current data.', error=None)
        except ValueError as exc:
            self.clear()
            self.progress(status='failed', error=str(exc))
        except Exception:
            self.clear()
            self.progress(status='failed', error='Could not verify the backup. Check connection, transfer quota, free disk space and backup compatibility.')
        finally:
            if release:
                with self.parent.lock:
                    self.parent.running = False

    def upload_start(self, data):
        with self.parent.lock:
            self.public()  # Remove expired uploads before checking availability.
            self.parent.idle()
            self.check_prepared_owner(data['owner_id'])
            if not self.parent.enabled or (self.parent.archive is not None and self.restore == appliance_restore):
                raise ValueError('Start the live server to restore a backup')
            name, size = data.get('filename'), data.get('size')
            if (not isinstance(name, str) or not re.fullmatch(r'[^/\\\x00-\x1f]{1,220}\.tar\.airlink', name)
                    or type(size) is not int or not 0 < size <= MAX_ARCHIVE_BYTES):
                raise ValueError('Choose an encrypted .tar.airlink backup, up to 20 GiB')
            self.parent.root.mkdir(mode=0o700, parents=True, exist_ok=True)
            if shutil.disk_usage(self.parent.root).free < size * 4:
                raise ValueError('Not enough free disk space to upload and restore this backup')
            self.clear()
            self.work.mkdir(mode=0o700)
            (self.work/'encrypted').touch(mode=0o600)
            cloud.atomic(self.parent.root/'restore.json', json.dumps({
                'status': 'uploading', 'source': 'file', 'filename': name, 'size': size, 'received': 0,
                'owner_id': data['owner_id'], 'token': secrets.token_hex(24), 'started_at': cloud.stamp(),
                'local_mode': self.parent.archive is not None,
                'expires_at': (datetime.now(timezone.utc)+timedelta(hours=1)).isoformat(),
            }).encode())
            return self.public(data['owner_id'])

    def check_prepared_owner(self, owner_id):
        state = self.public(owner_id)
        if state.get('status') == 'ready' and self.state().get('owner_id') != owner_id:
            raise ValueError('Another owner has prepared a recovery. Wait for it to be cancelled or expire.')

    def upload_state(self, data):
        state = self.public(data['owner_id'])
        if (state.get('status') != 'uploading' or not state.get('token')
                or not secrets.compare_digest(state['token'], str(data.get('token', '')))):
            raise ValueError('Upload expired or belongs to another owner. Browse and upload the file again.')
        return state

    def upload_chunk(self, data):
        with self.parent.lock:
            state = self.upload_state(data)
            encoded = data.get('data')
            if not isinstance(encoded, str) or not 1 <= len(encoded) <= 43692:
                raise ValueError('Invalid upload chunk size')
            try:
                chunk = base64.b64decode(encoded, validate=True)
            except ValueError:
                raise ValueError('Invalid upload data') from None
            offset = data.get('offset')
            if (type(offset) is not int or offset != state['received'] or not 0 < len(chunk) <= 32768
                    or offset + len(chunk) > state['size']):
                raise ValueError('Upload offset or length does not match. Browse and upload the file again.')
            with (self.work/'encrypted').open('ab') as output:
                output.write(chunk)
            self.progress(received=offset+len(chunk), expires_at=(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat())
            return {'received': offset+len(chunk)}

    def upload_prepare(self, data):
        with self.parent.lock:
            state = self.upload_state(data)
            password = data.get('password')
            if state['received'] != state['size'] or (self.work/'encrypted').stat().st_size != state['size']:
                raise ValueError('Upload is incomplete')
            if not isinstance(password, str) or not 12 <= len(password) <= 1024:
                raise ValueError('Enter the backup encryption password (12–1024 characters)')
            self.progress(status='checking')
            self.launch(self.verify, (password,))
            return self.public(data['owner_id'])

    def confirm(self, data):
        with self.parent.lock:
            self.parent.idle()
            state = self.public(data['owner_id'])
            if (state.get('status') != 'ready' or not state.get('token')
                    or not secrets.compare_digest(state['token'], str(data.get('token', '')))
                    or data.get('confirmation') != 'RESTORE'):
                raise ValueError('Verify a backup first, then type RESTORE to confirm replacing current data')
            self.progress(status='restoring', error=None)
            self.launch(self.restore_worker, ())
            return self.public(data['owner_id'])

    def restore_worker(self):
        try:
            self.validate(self.work/'data')
            result = self.restore(self.work/'data')
            self.progress(**result, finished_at=cloud.stamp())
        except ValueError as exc:
            self.progress(status='failed', error=str(exc))
        except Exception:
            self.progress(status='failed', error='Recovery failed. Check the local recovery logs and safety backup before retrying.')
        finally:
            with self.parent.lock:
                self.clear()
                self.parent.running = False

    def cancel(self, data):
        with self.parent.lock:
            if self.state().get('status') != 'uploading':
                self.parent.idle()
            if self.state().get('owner_id') != data['owner_id']:
                raise ValueError('Only the owner who prepared this recovery can cancel it')
            self.clear()
            self.progress(status='cancelled', token=None, error=None, message='Prepared recovery cancelled.')
            return self.public(data['owner_id'])

    def startup(self):
        with self.parent.lock:
            if self.state().get('status') in {'uploading', 'downloading', 'checking', 'restoring', 'ready'}:
                self.clear()
                self.progress(status='failed', token=None, error='Recovery interrupted by restart. Check current data before preparing another restore.')
