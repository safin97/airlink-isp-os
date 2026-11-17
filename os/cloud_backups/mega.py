"""MEGA transport via rclone. Credentials never appear in process arguments."""
from contextlib import contextmanager
from functools import lru_cache
import hashlib
import json
import re
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

from .service import atomic


class MegaError(ValueError):
    pass


def binary():
    configured = os.environ.get('AIRLINK_RCLONE_BIN')
    bundled = Path('/opt/airlink/tools/rclone')
    candidate = configured or (str(bundled) if bundled.is_file() else shutil.which('rclone'))
    return candidate if candidate and os.path.isfile(candidate) and os.access(candidate, os.X_OK) else None


def run(arguments, *, input=None, timeout=7200):
    executable = binary()
    if not executable:
        raise MegaError('MEGA transfer support is not installed. Install the AirLink update with rclone support.')
    # Ignore ambient rclone remotes, debugging and authentication overrides.
    environment = {key: value for key, value in os.environ.items() if not key.startswith('RCLONE_')}
    try:
        result = subprocess.run([executable, *arguments], input=input, capture_output=True,
                                text=True, timeout=timeout, env=environment)
    except (OSError, subprocess.TimeoutExpired):
        raise MegaError('MEGA transfer could not finish. Check your connection and retry.') from None
    if result.returncode:
        # Never echo subprocess output: it may include credentials or account data.
        error = (result.stderr or '').lower()
        if ("didn't find backend called" in error or "didn't find filing system for" in error) and 'mega' in error:
            raise MegaError('The installed transfer tool has no MEGA support. Install the latest AirLink update; changing your password will not fix this installation error.')
        raise MegaError('MEGA rejected the operation. Check your login, available storage and transfer quota. '
                        'Accounts requiring a one-time sign-in code are not supported for automatic backups.')
    return result.stdout


@lru_cache(maxsize=4)
def _backend_available(path, modified, size):
    try:
        run(['help', 'backend', 'mega'], timeout=15)
        return True
    except MegaError:
        return False


def backend_available():
    path = binary()
    if not path:
        return False
    try:
        stat = Path(path).stat()
    except OSError:
        return False
    return _backend_available(path, stat.st_mtime_ns, stat.st_size)


@contextmanager
def remote(config, root):
    if not backend_available():
        raise MegaError('MEGA support is missing from the installed transfer tool. Install the latest AirLink update before testing your account.')
    with tempfile.TemporaryDirectory(prefix='connection-', dir=root) as temporary:
        path = Path(temporary)/'rclone.conf'
        obscured = run(['obscure', '-'], input=config['account_password'] + '\n', timeout=15).strip()
        if not obscured or '\n' in obscured or '\r' in obscured:
            raise MegaError('Could not prepare MEGA credentials')
        atomic(path, ('[airlinkmega]\ntype = mega\nuser = ' + config['email'] +
                      '\npass = ' + obscured + '\nuse_https = true\n').encode())
        yield ['--config', str(path), '--cache-dir', str(Path(temporary)/'cache'),
               '--log-level', 'ERROR', '--stats', '0', '--retries', '1',
               '--low-level-retries', '2', '--contimeout', '20s', '--timeout', '2m']


def check_connection(config, root):
    with remote(config, root) as flags:
        # mkdir is idempotent and verifies login plus access to the chosen folder.
        run(['mkdir', 'airlinkmega:' + config['folder'], *flags], timeout=90)


def upload(config, path, root, progress):
    remote_folder = 'airlinkmega:' + config['folder']
    with remote(config, root) as flags:
        progress(status='uploading', total_bytes=path.stat().st_size)
        run(['copyto', str(path), remote_folder + '/' + path.name, '--immutable', *flags])
        # Space independent MEGA logins; the provider can throttle rapid reconnects.
        time.sleep(3)
        progress(status='verifying')
        # MEGA has no remote checksum API. Read back the encrypted bytes and compare.
        # The source directory contains exactly one encrypted file, never plaintext.
        run(['check', str(path.parent), remote_folder, '--download', '--one-way', *flags])
    digest = hashlib.sha256()
    with path.open('rb') as file:
        for block in iter(lambda: file.read(1024 * 1024), b''):
            digest.update(block)
    return {'filename': path.name, 'remote_path': config['folder'] + '/' + path.name,
            'size': path.stat().st_size, 'sha256': digest.hexdigest()}


def backup_name(name):
    return isinstance(name, str) and re.fullmatch(r'AirLink-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}\.tar\.airlink', name) is not None


def list_backups(config, root):
    with remote(config, root) as flags:
        rows = json.loads(run(['lsjson', 'airlinkmega:' + config['folder'],
                               '--files-only', '--max-depth', '1', *flags], timeout=90))
    result = []
    seen = set()
    for row in rows:
        name = row.get('Path')
        if row.get('IsDir') or not backup_name(name):
            continue
        if name in seen:
            raise MegaError('Duplicate backup filenames in MEGA. Rename duplicates before restoring.')
        seen.add(name)
        result.append({'filename': name, 'size': row.get('Size'), 'modified_at': row.get('ModTime')})
    return sorted(result, key=lambda item: item['filename'], reverse=True)[:500]


def download(config, name, destination, root):
    if not backup_name(name):
        raise MegaError('Select an AirLink backup from the MEGA backup folder')
    if destination.exists():
        raise MegaError('Recovery destination already exists')
    with remote(config, root) as flags:
        run(['copyto', 'airlinkmega:' + config['folder'] + '/' + name, str(destination),
             '--immutable', *flags])
    destination.chmod(0o600)
