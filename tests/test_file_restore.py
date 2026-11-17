import base64
import json
import sqlite3
import pytest
from fastapi import HTTPException
from airlink import api
from airlink.config import settings
from airlink.db import SessionLocal
from airlink.models import AuditLog
from cloud_backups import mega
from test_api import user
from test_mega_restore import recovery
from test_mega_backups import CONFIG, wait


def start(service, content, owner_id=1, filename='My saved backup.tar.airlink'):
    return service.action('restore.upload.start', {'owner_id': owner_id, 'filename': filename, 'size': len(content)})


def send(service, job, content, owner_id=1):
    for offset in range(0, len(content), 32768):
        block = content[offset:offset+32768]
        payload = {'owner_id': owner_id, 'token': job['token'], 'offset': offset,
                   'data': base64.b64encode(block).decode()}
        assert len(json.dumps({'action': 'backups.mega.restore.upload.chunk', 'payload': payload}).encode()) < 65536
        assert service.action('restore.upload.chunk', payload)['received'] == offset+len(block)


def test_file_restore_without_mega_or_rclone_keeps_data_until_confirmed_restart(recovery, monkeypatch):
    service, local, encrypted = recovery
    service.disconnect()
    monkeypatch.setattr(mega, 'binary', lambda: None)
    content = encrypted.read_bytes()
    before = local.database.read_bytes()
    job = start(service, content)
    assert job['source'] == 'file'
    send(service, job, content)
    service.action('restore.upload.prepare', {'owner_id': 1, 'token': job['token'], 'password': CONFIG['backup_password']})
    wait(service)
    state = service.recovery.public(1)
    assert state['status'] == 'ready'
    with pytest.raises(ValueError, match='Another owner'):
        start(service, content, owner_id=2)
    assert local.database.read_bytes() == before and not local.pending.exists()
    service.action('restore.confirm', {'owner_id': 1, 'token': job['token'], 'confirmation': 'RESTORE'})
    wait(service)
    assert service.recovery.state()['status'] == 'awaiting_restart'
    assert local.database.read_bytes() == before
    local.apply_pending(settings.encryption_key)
    assert service.recovery.state()['status'] == 'completed'
    with sqlite3.connect(local.database) as db:
        assert db.execute('PRAGMA integrity_check').fetchone() == ('ok',)
        assert db.execute('SELECT username FROM users').fetchone() == ('owner',)


def test_upload_token_offsets_limits_and_cancel(recovery):
    service, _, encrypted = recovery
    content = encrypted.read_bytes()
    job = start(service, content)
    payload = {'owner_id': 1, 'token': job['token'], 'offset': 0, 'data': base64.b64encode(content[:10]).decode()}
    for change in ({'owner_id': 2}, {'token': 'f'*48}, {'offset': 1}, {'offset': True},
                   {'data': '%%%notbase64'}, {'data': base64.b64encode(b'x'*32769).decode()}):
        with pytest.raises(ValueError): service.action('restore.upload.chunk', {**payload, **change})
    with pytest.raises(ValueError, match='incomplete'):
        service.action('restore.upload.prepare', {'owner_id': 1, 'token': job['token'], 'password': CONFIG['backup_password']})
    with pytest.raises(ValueError): start(service, content, owner_id=2)
    with pytest.raises(ValueError): service.queue()
    with pytest.raises(ValueError): service.recovery.cancel({'owner_id': 2})
    service.recovery.cancel({'owner_id': 1})
    assert not service.recovery.work.exists()
    job = start(service, content)
    service.recovery.progress(expires_at='2000-01-01T00:00:00+00:00')
    assert service.recovery.public(1)['status'] == 'expired'
    assert not service.recovery.work.exists()
    with pytest.raises(ValueError): service.action('restore.upload.chunk', {**payload, 'token': job['token']})


@pytest.mark.parametrize('filename', ['../escape.tar.airlink', 'C:\\backup.tar.airlink', 'backup.sql', 'bad\nname.tar.airlink'])
def test_upload_rejects_paths_and_unsupported_files(recovery, filename):
    service, _, _ = recovery
    with pytest.raises(ValueError): start(service, b'fake', filename=filename)


def test_wrong_password_fails_without_modifying_database(recovery):
    service, local, encrypted = recovery
    content = encrypted.read_bytes(); before = local.database.read_bytes()
    job = start(service, content); send(service, job, content)
    service.action('restore.upload.prepare', {'owner_id': 1, 'token': job['token'], 'password': 'incorrect-backup-password'})
    wait(service)
    assert service.recovery.state()['status'] == 'failed'
    assert not service.recovery.work.exists()
    assert local.database.read_bytes() == before


@pytest.mark.parametrize('role', ['manager', 'technician', 'viewer'])
def test_only_owners_can_upload_or_restore(client, owner, monkeypatch, role):
    _, headers = user(client, owner, role)
    monkeypatch.setattr(api, 'broker', lambda *args: pytest.fail('Unauthorized controller call'))
    for method, suffix, body in [('GET', '', None), ('POST', '/uploads', {'filename': 'backup.tar.airlink', 'size': 99}),
        ('PUT', '/uploads', {'token': 'a'*48, 'offset': 0, 'data': 'YQ=='}),
        ('POST', '/prepare', {'token': 'a'*48, 'password': CONFIG['backup_password']}),
        ('POST', '/confirm', {'token': 'a'*48, 'confirmation': 'RESTORE'}), ('POST', '/cancel', None)]:
        assert client.request(method, '/api/backups/restore'+suffix, headers=headers, json=body).status_code == 403


def test_owner_upload_api_and_removed_google_routes(client, owner, recovery, monkeypatch):
    service, _, encrypted = recovery
    def broker(action, payload):
        try: return service.action(action.removeprefix('backups.mega.'), payload)
        except ValueError as exc: raise HTTPException(409, str(exc))
    monkeypatch.setattr(api, 'broker', broker)
    content = encrypted.read_bytes()
    response = client.post('/api/backups/restore/uploads', headers=owner, json={'filename': 'backup.tar.airlink', 'size': len(content)})
    assert response.status_code == 201
    token = response.json()['token']
    for offset in range(0, len(content), 32768):
        response = client.put('/api/backups/restore/uploads', headers=owner,
            json={'token': token, 'offset': offset, 'data': base64.b64encode(content[offset:offset+32768]).decode()})
        assert response.status_code == 200
    response = client.post('/api/backups/restore/prepare', headers=owner, json={'token': token, 'password': CONFIG['backup_password']})
    assert response.status_code == 202
    wait(service)
    assert client.get('/api/backups/restore', headers=owner).json()['status'] == 'ready'
    assert client.post('/api/backups/restore/cancel', headers=owner).status_code == 200
    bad = client.post('/api/backups/restore/prepare', headers=owner, json={'token': token, 'password': 'private-secret'*100})
    assert bad.status_code == 422 and 'private-secret' not in bad.text
    with SessionLocal() as db:
        logs = [log.__dict__ for log in db.query(AuditLog).all()]
        assert CONFIG['backup_password'] not in str(logs) and token not in str(logs)
    assert not any('/backups/google-drive' in route.path for route in api.app.routes)
    assert client.post('/api/backups/google-drive/run', headers=owner).status_code == 404
