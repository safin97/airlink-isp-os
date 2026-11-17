"""Stage local recovery, then apply before opening the application database."""
import json
import os
from pathlib import Path
import secrets
import shutil
import sqlite3
from cryptography.fernet import Fernet
from cloud_backups.service import atomic, stamp


class LocalRestore:
    def __init__(self, root, database):
        self.root, self.database = Path(root), Path(database)
        self.pending = self.root/'pending-restore'
        self.key_file = self.root/'local-recovery-key'

    def validate(self, directory):
        metadata = json.loads((directory/'recovery.json').read_text())
        if metadata.get('format') != 'airlink-local-sqlite-v1':
            raise ValueError('This is not a supported local AirLink backup')
        Fernet(metadata['encryption_key'].encode())
        with sqlite3.connect((directory/'database.sqlite').as_uri()+'?mode=ro', uri=True) as backup:
            if backup.execute('PRAGMA quick_check').fetchall() != [('ok',)]:
                raise ValueError('SQLite backup integrity check failed')
            if backup.execute('PRAGMA foreign_key_check').fetchone():
                raise ValueError('SQLite backup contains broken database relationships')
            tables = {row[0] for row in backup.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if not {'users', 'roles', 'initialization', 'login_sessions', 'refresh_tokens'} <= tables:
                raise ValueError('Backup is missing required AirLink data')
            if not backup.execute("SELECT 1 FROM users WHERE role='owner' AND active=1 LIMIT 1").fetchone():
                raise ValueError('Backup must contain an active owner account')
            if self.database.exists():
                with sqlite3.connect(self.database.as_uri()+'?mode=ro', uri=True) as current:
                    # New tables can be created on startup; changed existing columns need a migration.
                    for name in tables:
                        quoted = '"' + name.replace('"', '""') + '"'
                        required = {row[1] for row in current.execute('PRAGMA table_info('+quoted+')')}
                        existing = {row[1] for row in backup.execute('PRAGMA table_info('+quoted+')')}
                        if not required <= existing:
                            raise ValueError('Backup schema is older than this local application. Recover it with the matching AirLink version first.')
        return metadata

    def stage(self, directory):
        self.validate(directory)
        if self.pending.exists():
            raise ValueError('A local restore is already waiting for restart')
        temporary = self.root/('staging-'+secrets.token_hex(8))
        try:
            shutil.copytree(directory, temporary)
            temporary.rename(self.pending)
        finally:
            if temporary.exists(): shutil.rmtree(temporary)
        return {'status': 'awaiting_restart',
                'message': 'Restore is ready. Stop the local server and run ./scripts/live.sh again. '
                           'A safety copy will be saved before replacement. Sign in with an account from the backup.'}

    def apply_pending(self, current_key):
        # Called only at startup while holding the local server's exclusive process lock.
        if self.key_file.exists():
            current_key = self.key_file.read_text().strip()
        if not self.pending.exists():
            return self.key_file.read_text().strip() if self.key_file.exists() else current_key
        metadata = self.validate(self.pending)
        safety = self.pending/'safety-path'
        if not safety.exists():
            destination = self.root/('before-restore-'+secrets.token_hex(12))
            destination.mkdir(mode=0o700)
            if self.database.exists():
                with sqlite3.connect(self.database) as source, sqlite3.connect(destination/'database.sqlite') as target:
                    source.backup(target)
                (destination/'database.sqlite').chmod(0o600)
            atomic(destination/'recovery.json', json.dumps({
                'format': 'airlink-local-sqlite-v1', 'encryption_key': current_key}).encode())
            atomic(safety, str(destination).encode())
        else:
            destination = Path(safety.read_text())
        replacement = self.database.with_name(self.database.name+'.restore-'+secrets.token_hex(8))
        try:
            with sqlite3.connect(self.pending/'database.sqlite') as source, sqlite3.connect(replacement) as target:
                source.backup(target)
                target.execute('DELETE FROM refresh_tokens')
                target.execute('DELETE FROM login_sessions')
                target.commit()
            replacement.chmod(0o600)
            # No application connections exist yet. Remove stale SQLite sidecars before swapping.
            for suffix in ('-wal', '-shm', '-journal'):
                self.database.with_name(self.database.name+suffix).unlink(missing_ok=True)
            os.replace(replacement, self.database)
            atomic(self.key_file, metadata['encryption_key'].encode())
            state_path = self.root/'restore.json'
            state = json.loads(state_path.read_text()) if state_path.exists() else {}
            state.update(status='completed', token=None, error=None, finished_at=stamp(),
                         safety_backup=str(destination), message='Local database restored. Sign in with an account from the backup.')
            atomic(state_path, json.dumps(state).encode())
            shutil.rmtree(self.pending)
        finally:
            replacement.unlink(missing_ok=True)
        return metadata['encryption_key']
