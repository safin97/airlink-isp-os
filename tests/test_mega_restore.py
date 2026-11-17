import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tarfile
import time
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from airlink import api, local_backup
from airlink.db import engine
from airlink.local_restore import LocalRestore
from airlink.config import settings
from cloud_backups import mega, mega_service, mega_restore
from recovery.cloud_archive import transform
from recovery.verified_archive import extract
from test_api import user
from test_mega_backups import CONFIG, connect, wait

NAME = 'AirLink-20261117T120000Z-abcdef01.tar.airlink'


@pytest.fixture
def recovery(tmp_path, monkeypatch, owner):
    root = tmp_path/'mega'
    current = tmp_path/'current.sqlite'
    with sqlite3.connect(engine.url.database) as source, sqlite3.connect(current) as target:
        source.backup(target)
    local = LocalRestore(root, current)
    service = mega_service.MegaBackupService(root, archive=local_backup.archive,
        restore_validate=local.validate, restore_apply=local.stage)
    monkeypatch.setattr(mega, 'binary', lambda: '/usr/bin/rclone')
    monkeypatch.setattr(mega, 'backend_available', lambda: bool(mega.binary()))
    monkeypatch.setattr(mega, 'check_connection', lambda *args: None)
    monkeypatch.setattr(mega.time, 'sleep', lambda _: None)
    connect(service)
    archive = tmp_path/'backup.tar'
    local_backup.archive(archive)
    encrypted = tmp_path/'backup.airlink'
    transform(archive, encrypted, CONFIG['backup_password'])
    monkeypatch.setattr(mega, 'list_backups', lambda *args: [{'filename': NAME, 'size': encrypted.stat().st_size}])
    monkeypatch.setattr(mega, 'download', lambda config, name, target, root: shutil.copyfile(encrypted, target))
    yield service, local, encrypted
    service.stop()


def prepare(service, password=CONFIG['backup_password']):
    service.action('restore.prepare', {'filename': NAME, 'password': password, 'owner_id': 1})
    wait(service)
    return service.action('restore.status', {'owner_id': 1})


def test_complete_local_recovery_saves_safety_copy_and_revokes_sessions(recovery):
    service, local, encrypted = recovery
    with sqlite3.connect(local.database) as db:
        db.execute("UPDATE users SET username='after-backup'")
        db.commit()
    before = local.database.read_bytes()
    state = prepare(service)
    assert state['status'] == 'ready'
    assert local.database.read_bytes() == before
    assert 'token' not in service.status()['restore']
    assert 'token' not in service.recovery.public(2)
    assert not (service.recovery.work/'encrypted').exists()
    service.action('restore.confirm', {'owner_id': 1, 'token': state['token'], 'confirmation': 'RESTORE'})
    wait(service)
    assert service.recovery.state()['status'] == 'awaiting_restart'
    assert local.database.read_bytes() == before
    with pytest.raises(ValueError): service.queue()
    with pytest.raises(ValueError): service.recovery.cancel({'owner_id': 1})
    assert local.apply_pending(settings.encryption_key) == settings.encryption_key
    state = service.recovery.public(1)
    assert state['status'] == 'completed'
    with sqlite3.connect(local.database) as db:
        assert db.execute('SELECT username FROM users').fetchone() == ('owner',)
        assert db.execute('SELECT count(*) FROM login_sessions').fetchone() == (0,)
        assert db.execute('SELECT count(*) FROM refresh_tokens').fetchone() == (0,)
        assert db.execute('PRAGMA integrity_check').fetchone() == ('ok',)
    with sqlite3.connect(Path(state['safety_backup'])/'database.sqlite') as db:
        assert db.execute('SELECT username FROM users').fetchone() == ('after-backup',)
    assert (local.key_file).stat().st_mode & 0o777 == 0o600
    assert not local.pending.exists()
    assert local.apply_pending('ignored-default') == settings.encryption_key


@pytest.mark.parametrize('failure', ['password', 'corrupt', 'missing'])
def test_failed_verification_never_modifies_current_database(recovery, monkeypatch, failure):
    service, local, encrypted = recovery
    before = local.database.read_bytes()
    if failure == 'corrupt':
        contents = encrypted.read_bytes()
        encrypted.write_bytes(contents[:-1]+bytes([contents[-1]^1]))
    if failure == 'missing': monkeypatch.setattr(mega, 'list_backups', lambda *args: [])
    state = prepare(service, 'incorrect-password' if failure == 'password' else CONFIG['backup_password'])
    assert state['status'] == 'failed'
    assert local.database.read_bytes() == before
    assert not service.recovery.work.exists()
    assert CONFIG['backup_password'] not in json.dumps(state)
    with pytest.raises(ValueError):
        service.recovery.confirm({'owner_id': 1, 'token': state['token'], 'confirmation': 'RESTORE'})


def test_confirmation_is_owner_bound_exact_and_expires(recovery):
    service, _, _ = recovery
    state = prepare(service)
    for change in ({'owner_id': 2}, {'confirmation': 'yes'}, {'token': 'a'*48}):
        with pytest.raises(ValueError):
            service.recovery.confirm({'owner_id': 1, 'token': state['token'], 'confirmation': 'RESTORE', **change})
    service.recovery.progress(expires_at='2020-01-01T00:00:00+00:00')
    assert service.recovery.public(1)['status'] == 'expired'
    assert not service.recovery.work.exists()
    with pytest.raises(ValueError):
        service.recovery.confirm({'owner_id': 1, 'token': state['token'], 'confirmation': 'RESTORE'})


def test_cancel_and_restart_remove_prepared_plaintext(recovery):
    service, _, _ = recovery
    prepare(service)
    service.action('restore.cancel', {'owner_id': 1})
    assert not service.recovery.work.exists()
    assert service.recovery.state()['status'] == 'cancelled'
    prepare(service)
    service.recovery.startup()
    assert service.recovery.state()['status'] == 'failed'
    assert not service.recovery.work.exists()


@pytest.mark.parametrize('unsafe', ['path', 'symlink', 'duplicate', 'missing', 'checksum', 'wrong-platform'])
def test_archive_rejects_unsafe_or_incompatible_members(tmp_path, unsafe):
    source = tmp_path/'archive.tar'
    contents = {'database.sqlite': b'data', 'recovery.json': b'{}', 'README.txt': b'read'}
    contents['SHA256SUMS'] = ''.join(hashlib.sha256(value).hexdigest()+'  '+name+'\n' for name, value in contents.items()).encode()
    with tarfile.open(source, 'w') as bundle:
        for name, value in contents.items():
            if unsafe == 'missing' and name == 'README.txt': continue
            info = tarfile.TarInfo('../escape' if unsafe == 'path' and name == 'README.txt' else name)
            if unsafe == 'symlink' and name == 'README.txt':
                info.type = tarfile.SYMTYPE; info.linkname = '/etc/passwd'
                bundle.addfile(info); continue
            if unsafe == 'checksum' and name == 'README.txt': value = b'changed'
            info.size = len(value); bundle.addfile(info, io.BytesIO(value))
            if unsafe == 'duplicate': bundle.addfile(info, io.BytesIO(value))
    with pytest.raises(ValueError): extract(source, tmp_path/'out', unsafe != 'wrong-platform')
    assert not (tmp_path/'escape').exists()


def test_transport_lists_only_backups_and_download_stays_in_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(mega, 'backend_available', lambda: True)
    calls = []
    def run(args, **kwargs):
        calls.append(args)
        if args[0] == 'obscure': return 'obscured'
        if args[0] == 'lsjson': return json.dumps([
            {'Path': NAME, 'Size': 99, 'ModTime': 'today'},
            {'Path': '../'+NAME}, {'Path': 'other.txt'}, {'Path': 'nested/'+NAME}])
        if args[0] == 'copyto': Path(args[2]).write_bytes(b'encrypted')
    monkeypatch.setattr(mega, 'run', run)
    assert mega.list_backups(CONFIG, tmp_path) == [{'filename': NAME, 'size': 99, 'modified_at': 'today'}]
    mega.download(CONFIG, NAME, tmp_path/'download', tmp_path)
    assert calls[-1][1] == 'airlinkmega:'+CONFIG['folder']+'/'+NAME
    with pytest.raises(ValueError): mega.download(CONFIG, '../'+NAME, tmp_path/'unsafe', tmp_path)
    assert not list(tmp_path.glob('connection-*'))
    monkeypatch.setattr(mega, 'run', lambda args, **kw: 'obscured' if args[0] == 'obscure' else json.dumps([{'Path': NAME}]*2))
    with pytest.raises(ValueError, match='Duplicate'): mega.list_backups(CONFIG, tmp_path)


@pytest.mark.parametrize('role', ['manager', 'technician', 'viewer'])
def test_restore_endpoints_are_owner_only(client, owner, monkeypatch, role):
    _, headers = user(client, owner, role)
    monkeypatch.setattr(api, 'broker', lambda *args: pytest.fail('must not reach controller'))
    for method, suffix, body in [('GET', '/files', None), ('GET', '/restore', None),
        ('POST', '/restore/prepare', {'filename': NAME, 'password': CONFIG['backup_password']}),
        ('POST', '/restore/confirm', {'token': 'a'*48, 'confirmation': 'RESTORE'}),
        ('POST', '/restore/cancel', None)]:
        assert client.request(method, '/api/backups/mega'+suffix, headers=headers, json=body).status_code == 403


def test_owner_api_prepare_and_invalid_secret_redaction(client, owner, recovery, monkeypatch):
    service, local, _ = recovery
    def broker(action, payload):
        try: return service.action(action.removeprefix('backups.mega.'), payload)
        except ValueError as exc: raise HTTPException(409, str(exc))
    monkeypatch.setattr(api, 'broker', broker)
    assert client.get('/api/backups/mega/files', headers=owner).json()['files'][0]['filename'] == NAME
    response = client.post('/api/backups/mega/restore/prepare', headers=owner,
        json={'filename': NAME, 'password': CONFIG['backup_password']})
    assert response.status_code == 202
    wait(service)
    assert client.get('/api/backups/mega/restore', headers=owner).json()['status'] == 'ready'
    response = client.post('/api/backups/mega/restore/prepare', headers=owner,
        json={'filename': NAME, 'password': 'private-secret'*100})
    assert response.status_code == 422 and 'private-secret' not in response.text
    assert client.post('/api/backups/mega/restore/cancel', headers=owner).status_code == 200
    assert not local.pending.exists()


def test_appliance_uses_existing_protected_restore_script(tmp_path, monkeypatch):
    backups = tmp_path/'backups'; backups.mkdir()
    data = tmp_path/'data'; data.mkdir(); (data/'database.dump').write_bytes(b'dump')
    real_path = Path
    monkeypatch.setattr(mega_restore, 'Path', lambda value: backups if value == '/var/backups/airlink' else real_path(value))
    calls = []
    monkeypatch.setattr(mega_restore.subprocess, 'run', lambda args, **kw: calls.append(args) or SimpleNamespace(returncode=0))
    assert mega_restore.appliance_restore(data)['status'] == 'completed'
    assert calls[0][0:2] == ['bash', '/opt/airlink/os/recovery/restore.sh']
    assert calls[0][-1] == 'RESTORE' and Path(calls[0][2]).parent == backups


@pytest.mark.parametrize('migration_fails', [False, True])
def test_appliance_restore_runs_migrations_and_rolls_back_on_failure(tmp_path, migration_fails):
    project = Path(__file__).resolve().parents[1]
    backups = tmp_path/'backups'; backups.mkdir()
    selected = backups/'selected'; selected.mkdir()
    safety = backups/'safety'; safety.mkdir()
    (selected/'database.dump').write_text('selected database')
    (safety/'database.dump').write_text('original database')
    (selected/'SHA256SUMS').write_text(hashlib.sha256(b'selected database').hexdigest()+'  database.dump\n')
    commands = tmp_path/'bin'; commands.mkdir()
    def script(path, body):
        path.write_text('#!/bin/bash\nset -eu\n'+body); path.chmod(0o700)
    script(commands/'realpath', 'printf "%s\\n" "$1"\n')
    script(commands/'sha256sum', 'exit 0\n')  # Checksums are separately tested above.
    script(commands/'flock', 'exit 0\n')
    script(commands/'systemctl', 'echo "$*" >> "$RESTORE_TEST_LOG"\n')
    script(commands/'runuser', 'if [[ "$*" == *pg_restore* ]]; then cat >> "$RESTORE_TEST_LOG"; echo >> "$RESTORE_TEST_LOG"; else echo sessions-cleared >> "$RESTORE_TEST_LOG"; fi\n')
    backup_script = tmp_path/'backup.sh'
    script(backup_script, 'echo safety-created >> "$RESTORE_TEST_LOG"\nprintf "%s\\n" "$RESTORE_TEST_SAFETY"\n')
    migration_script = tmp_path/'migrate.sh'
    script(migration_script, 'echo migrated >> "$RESTORE_TEST_LOG"\nexit '+('1' if migration_fails else '0')+'\n')
    restore_script = tmp_path/'restore.sh'
    restore_script.write_text((project/'os/recovery/restore.sh').read_text()
        .replace('/var/backups/airlink', str(backups))
        .replace('/opt/airlink/os/recovery/backup.sh', str(backup_script))
        .replace('/opt/airlink/deployment/migrate.sh', str(migration_script))
        .replace('/bin/bash /opt/airlink/deployment/health.sh', 'true'))
    log = tmp_path/'operations'
    result = subprocess.run(['bash', str(restore_script), str(selected), 'RESTORE'], capture_output=True,
        env={**os.environ, 'PATH': str(commands)+':'+os.environ['PATH'], 'AIRLINK_MAINTENANCE_FD': '9',
             'RESTORE_TEST_LOG': str(log), 'RESTORE_TEST_SAFETY': str(safety)})
    assert result.returncode == (1 if migration_fails else 0), result.stderr
    events = log.read_text().splitlines()
    assert events[:4] == ['stop airlink-api airlink-monitor airlink-alerts', 'safety-created', 'selected database', 'migrated']
    assert events[4] == ('original database' if migration_fails else 'sessions-cleared')
    assert events[-1] == 'start airlink-api airlink-monitor airlink-alerts'
