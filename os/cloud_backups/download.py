"""Password-encrypted owner downloads, independent of Google OAuth."""
import base64
from contextlib import nullcontext
import hashlib
from pathlib import Path
import re
import secrets
import shutil
import tempfile
import threading
import time

from . import service as cloud
from recovery.cloud_archive import transform

CHUNK = 256 * 1024  # Fits the controller's one-megabyte JSON response limit.
TTL = 3600


class DownloadService:
    def __init__(self, root=Path('/var/lib/airlink-system/backup-downloads'), archive=None):
        self.root = Path(root)
        self.archive = archive
        self.lock = threading.RLock()
        self.jobs = {}
        self.running = False

    def cleanup(self):
        for job_id, job in list(self.jobs.items()):
            if job['status'] != 'creating' and job['expires'] <= time.time():
                shutil.rmtree(self.root / job_id, ignore_errors=True)
                del self.jobs[job_id]
        # Remove abandoned files from previous controller processes after one hour.
        if self.root.exists():
            for path in self.root.iterdir():
                if (re.fullmatch(r'[a-f0-9]{32}', path.name) and path.name not in self.jobs
                        and not path.is_symlink() and path.stat().st_mtime < time.time() - TTL):
                    shutil.rmtree(path, ignore_errors=True)

    def public(self, job):
        return {key: value for key, value in job.items() if key != 'owner_id'}

    def job(self, job_id, owner_id):
        self.cleanup()
        job = self.jobs.get(job_id)
        if not job or job['owner_id'] != owner_id:
            raise ValueError('Backup expired or unavailable. Create a new backup.')
        return job

    def create(self, owner_id, password):
        if not isinstance(password, str) or not 12 <= len(password) <= 1024:
            raise ValueError('Use a backup password with 12–1024 characters')
        with self.lock:
            self.cleanup()
            if self.running:
                raise ValueError('A download backup is already being created. Try again when it finishes.')
            self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
            job_id = secrets.token_hex(16)
            (self.root / job_id).mkdir(mode=0o700)
            job = dict(id=job_id, owner_id=owner_id, status='creating', expires=time.time() + TTL)
            self.jobs[job_id] = job
            self.running = True
            try:
                threading.Thread(target=self.build, args=(job_id, password), daemon=True,
                                 name='download-backup').start()
            except Exception:
                self.running = False
                del self.jobs[job_id]
                shutil.rmtree(self.root / job_id, ignore_errors=True)
                raise ValueError('Cannot start the backup worker. Try again.') from None
            return self.public(job)

    def build(self, job_id, password):
        directory = self.root / job_id
        destination = directory / 'backup.tar.airlink'
        try:
            with (cloud.maintenance() if self.archive is None else nullcontext()):
                with tempfile.TemporaryDirectory(prefix='work-', dir=directory) as temporary:
                    source = Path(temporary) / 'backup.tar'
                    (self.archive or cloud.archive)(source)
                    transform(source, destination, password)
            digest = hashlib.sha256()
            with destination.open('rb') as file:
                for block in iter(lambda: file.read(CHUNK), b''):
                    digest.update(block)
            with self.lock:
                self.jobs[job_id].update(status='ready', size=destination.stat().st_size,
                    sha256=digest.hexdigest(), filename='AirLink-' + job_id + '.tar.airlink',
                    expires=time.time() + TTL)
        except Exception:
            destination.unlink(missing_ok=True)
            with self.lock:
                self.jobs[job_id].update(status='failed',
                    error='Backup creation failed. Check free disk space and local maintenance services, then try again.')
        finally:
            with self.lock:
                self.running = False

    def action(self, name, payload):
        owner_id = payload['owner_id']
        if name == 'create':
            return self.create(owner_id, payload.get('password'))
        with self.lock:
            job = self.job(payload.get('id'), owner_id)
            if name == 'status':
                return self.public(job)
            if name == 'chunk':
                if job['status'] != 'ready':
                    raise ValueError('Backup is not ready to download')
                offset = payload.get('offset', 0)
                if type(offset) is not int or not 0 <= offset <= job['size']:
                    raise ValueError('Invalid backup offset')
                with (self.root / job['id'] / 'backup.tar.airlink').open('rb') as file:
                    file.seek(offset)
                    return {'data': base64.b64encode(file.read(CHUNK)).decode()}
            raise ValueError('Unknown download backup action')


service = DownloadService()
