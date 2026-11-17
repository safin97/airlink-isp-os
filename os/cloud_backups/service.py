"""Shared archive, scheduling and private storage helpers for AirLink backups."""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
from zoneinfo import ZoneInfo
from updates import update

BACKUPS = Path('/var/backups/airlink')
BACKUP_SCRIPT = '/opt/airlink/os/recovery/backup.sh'
UTC = timezone.utc


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
