import hashlib
import json
import sqlite3
import tarfile
import threading
import time
from types import SimpleNamespace

import pytest
from airlink import api, local_backup
from airlink.config import settings
from airlink.db import SessionLocal
from airlink.models import AuditLog
from cloud_backups.download import DownloadService, CHUNK
from recovery.cloud_archive import transform
from test_api import user

PASSWORD = 'download-recovery-password'


@pytest.fixture
def downloads(tmp_path, monkeypatch):
    service = DownloadService(tmp_path/'downloads', archive=local_backup.archive)
    def broker(action, payload):
        from fastapi import HTTPException
        try:
            return service.action(action.removeprefix('backups.downloads.'), payload)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None
    monkeypatch.setattr(api, 'broker', broker)
    return service


def ready(service, job):
    deadline = time.monotonic() + 10
    while service.running and time.monotonic() < deadline:
        time.sleep(0.01)
    assert not service.running
    return service.jobs[job['id']]


def test_download_roundtrip_contains_consistent_database_and_recovery_key(client, owner, downloads, tmp_path):
    response = client.post('/api/backups/downloads', headers=owner, json={'password': PASSWORD})
    assert response.status_code == 202, response.text
    job = response.json()
    assert PASSWORD not in response.text
    completed = ready(downloads, job)
    assert completed['status'] == 'ready'
    result = client.get('/api/backups/downloads/'+job['id'], headers=owner)
    assert result.status_code == 200 and 'owner_id' not in result.json()
    response = client.get('/api/backups/downloads/'+job['id']+'/file', headers=owner)
    assert response.status_code == 200
    assert response.headers['cache-control'] == 'no-store'
    assert len(response.content) == completed['size']
    assert hashlib.sha256(response.content).hexdigest() == response.headers['x-backup-sha256']
    assert response.headers['content-disposition'].endswith('.tar.airlink"')
    assert settings.encryption_key.encode() not in response.content
    encrypted = tmp_path/'backup.airlink'; encrypted.write_bytes(response.content)
    recovered = tmp_path/'recovered.tar'
    transform(encrypted, recovered, PASSWORD, decrypt=True)
    with tarfile.open(recovered) as archive:
        assert set(archive.getnames()) == {'database.sqlite', 'recovery.json', 'SHA256SUMS', 'README.txt'}
        recovery = json.load(archive.extractfile('recovery.json'))
        assert recovery['encryption_key'] == settings.encryption_key
        assert recovery['format'] == 'airlink-local-sqlite-v1'
        sums = archive.extractfile('SHA256SUMS').read().decode().splitlines()
        for line in sums:
            digest, name = line.split()
            assert hashlib.sha256(archive.extractfile(name).read()).hexdigest() == digest
        database = tmp_path/'restored.sqlite'
        database.write_bytes(archive.extractfile('database.sqlite').read())
    with sqlite3.connect(database) as db:
        assert db.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        assert db.execute("SELECT username FROM users WHERE role='owner'").fetchone()[0] == 'owner'
    stored = downloads.root/job['id']/'backup.tar.airlink'
    assert stored.stat().st_mode & 0o777 == 0o600
    assert list(stored.parent.iterdir()) == [stored]
    with SessionLocal() as db:
        logs = db.query(AuditLog).all()
        assert any(log.action == 'backup.download.create' for log in logs)
        assert PASSWORD not in str([log.__dict__ for log in logs])


@pytest.mark.parametrize('role', ['manager', 'technician', 'viewer'])
def test_nonowners_cannot_create_inspect_or_download(client, owner, role, monkeypatch):
    _, headers = user(client, owner, role)
    monkeypatch.setattr(api, 'broker', lambda *args: pytest.fail('must not reach controller'))
    for method, path in [('POST', ''), ('GET', '/any'), ('GET', '/any/file')]:
        response = client.request(method, '/api/backups/downloads'+path, headers=headers,
                                  **({'json': {'password': PASSWORD}} if method == 'POST' else {}))
        assert response.status_code == 403


def test_unauthenticated_and_secret_validation(client, owner, monkeypatch):
    monkeypatch.setattr(api, 'broker', lambda *args: pytest.fail('must not reach controller'))
    for password in ['too-short', 'private-' * 200]:
        response = client.post('/api/backups/downloads', headers=owner, json={'password': password})
        assert response.status_code == 422 and password not in response.text
    client.cookies.clear()
    assert client.get('/api/backups/downloads/any/file').status_code == 401
    assert client.post('/api/backups/downloads', json={'password': PASSWORD}).status_code == 401


def test_job_ownership_chunks_expiry_and_wrong_password(tmp_path):
    def archive(path): path.write_bytes(b'database-contents' * CHUNK)
    service = DownloadService(tmp_path/'downloads', archive=archive)
    job = service.create('owner1', PASSWORD)
    completed = ready(service, job)
    assert completed['status'] == 'ready'
    for action in ('status', 'chunk'):
        with pytest.raises(ValueError, match='unavailable'):
            service.action(action, {'owner_id': 'other-owner', 'id': job['id']})
    for ident in ('../../elsewhere', 'unknown'):
        with pytest.raises(ValueError): service.action('chunk', {'owner_id': 'owner1', 'id': ident})
    for offset in (-1, True, '0', completed['size'] + 1):
        with pytest.raises(ValueError):
            service.action('chunk', {'owner_id': 'owner1', 'id': job['id'], 'offset': offset})
    import base64
    content = b''.join(base64.b64decode(service.action('chunk',
        {'owner_id': 'owner1', 'id': job['id'], 'offset': offset})['data'])
        for offset in range(0, completed['size'], CHUNK))
    assert hashlib.sha256(content).hexdigest() == completed['sha256']
    encrypted = service.root/job['id']/'backup.tar.airlink'
    with pytest.raises(Exception): transform(encrypted, tmp_path/'bad.tar', 'wrong-password', decrypt=True)
    assert not (tmp_path/'bad.tar').exists()
    completed['expires'] = 0
    with pytest.raises(ValueError): service.action('status', {'owner_id': 'owner1', 'id': job['id']})
    assert not encrypted.parent.exists()


def test_failure_removes_plaintext_and_does_not_expose_error_secrets(tmp_path):
    def fail(path):
        path.write_bytes(b'secret-plaintext')
        raise ValueError('secret-credentials')
    service = DownloadService(tmp_path/'downloads', archive=fail)
    job = service.create('owner', PASSWORD)
    completed = ready(service, job)
    assert completed['status'] == 'failed'
    assert 'secret' not in completed['error']
    assert not list((service.root/job['id']).iterdir())
    with pytest.raises(ValueError, match='not ready'):
        service.action('chunk', {'owner_id': 'owner', 'id': job['id']})


def test_concurrent_creation_rejected_and_worker_start_failure_cleans_up(tmp_path, monkeypatch):
    from cloud_backups import download
    gate = threading.Event()
    def archive(path):
        assert gate.wait(5)
        path.write_bytes(b'data')
    service = DownloadService(tmp_path/'downloads', archive=archive)
    job = service.create('owner', PASSWORD)
    try:
        with pytest.raises(ValueError, match='already'): service.create('owner', PASSWORD)
    finally:
        gate.set()
    ready(service, job)
    def fail(): raise RuntimeError('thread unavailable')
    monkeypatch.setattr(download.threading, 'Thread', lambda **kw: SimpleNamespace(start=fail))
    with pytest.raises(ValueError, match='Cannot start'): service.create('owner', PASSWORD)
    assert not service.running and len(service.jobs) == 1
