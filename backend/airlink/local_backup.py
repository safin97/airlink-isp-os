"""Consistent SQLite archive for the local development launcher only."""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tarfile
import tempfile


def archive(destination):
    from .db import engine
    from .config import settings
    if engine.url.get_backend_name() != 'sqlite' or not engine.url.database:
        raise ValueError('Local backup requires a file-backed SQLite database')
    with tempfile.TemporaryDirectory(dir=Path(destination).parent) as temporary:
        work = Path(temporary)
        with sqlite3.connect(engine.url.database) as source, sqlite3.connect(work/'database.sqlite') as target:
            source.backup(target)
        (work/'recovery.json').write_text(json.dumps({
            'format': 'airlink-local-sqlite-v1',
            'encryption_key': settings.encryption_key,
        }))
        (work/'README.txt').write_text(
            'Local AirLink SQLite backup; not an appliance PostgreSQL backup.\n'
            'Stop the local server before recovery. Preserve your current database first.\n'
            'Restore database.sqlite as /tmp/airlink-browser-qa.sqlite and set\n'
            'AIRLINK_ENCRYPTION_KEY to encryption_key from recovery.json when starting\n'
            'the local launcher. Restart and sign in again. Keep all extracted files private.\n')
        names = ['database.sqlite', 'recovery.json', 'README.txt']
        sums = []
        for name in names:
            os.chmod(work/name, 0o600)
            digest = hashlib.sha256()
            with (work/name).open('rb') as file:
                for block in iter(lambda: file.read(1024 * 1024), b''):
                    digest.update(block)
            sums.append(digest.hexdigest() + '  ' + name)
        (work/'SHA256SUMS').write_text('\n'.join(sums) + '\n')
        with tarfile.open(destination, 'w') as bundle:
            for name in [*names, 'SHA256SUMS']:
                bundle.add(work/name, arcname=name, recursive=False)
