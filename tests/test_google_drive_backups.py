import hashlib
import json
import tarfile
import threading
from contextlib import nullcontext
from datetime import datetime, timezone
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
from cryptography.exceptions import InvalidTag
from cloud_backups import service as cloud, google_drive as drive
from recovery.cloud_archive import transform, CHUNK
from airlink import api
from airlink.db import SessionLocal
from airlink.models import AuditLog
from test_api import user
from test_section_access import grant
from airlink.section_access import ASSIGNABLE

CONFIG = dict(client_id='1234567890-airlink.apps.googleusercontent.com', client_secret='test-client-secret',
              redirect_uri='https://airlink.example.com'+cloud.CALLBACK, folder_name='AirLink Backups',
              backup_password='offline-recovery-password', automatic_enabled=True,
              weekday=6, time='02:00', timezone='Europe/Zurich')


@pytest.fixture
def worker(tmp_path, monkeypatch):
    monkeypatch.setattr(cloud, 'ROOT', tmp_path/'settings')
    monkeypatch.setattr(cloud, 'BACKUPS', tmp_path/'local-backups')
    script = tmp_path/'backup.sh'; script.touch()
    monkeypatch.setattr(cloud, 'BACKUP_SCRIPT', str(script))
    service = cloud.BackupService()
    yield service
    service.stop()


def connected(worker):
    worker.configure(CONFIG)
    config = cloud.configuration()
    config.update(refresh_token='refresh-private', folder_id='folder123', account_email='owner@example.com')
    cloud.save_config(config)
    return config


def test_encrypted_backup_roundtrip_and_permissions(tmp_path):
    plain = tmp_path/'backup.tar'; plain.write_bytes(b'private-db-and-config\x00' * (CHUNK//10))
    encrypted, recovered = tmp_path/'backup.airlink', tmp_path/'recovered.tar'
    transform(plain, encrypted, CONFIG['backup_password'])
    assert b'private-db-and-config' not in encrypted.read_bytes()
    assert encrypted.stat().st_mode & 0o777 == 0o600
    transform(encrypted, recovered, CONFIG['backup_password'], decrypt=True)
    assert plain.read_bytes() == recovered.read_bytes()
    assert recovered.stat().st_mode & 0o777 == 0o600
    with pytest.raises(ValueError, match='already exists'):
        transform(encrypted, recovered, CONFIG['backup_password'], decrypt=True)


@pytest.mark.parametrize('damage', ['password', 'header', 'body', 'truncated'])
def test_authentication_failure_never_publishes_plaintext(tmp_path, damage):
    plain = tmp_path/'input'; plain.write_bytes(b'secret database' * 500)
    encrypted, output = tmp_path/'encrypted', tmp_path/'output'
    transform(plain, encrypted, CONFIG['backup_password'])
    contents = bytearray(encrypted.read_bytes())
    if damage == 'header': contents[0] ^= 1
    if damage == 'body': contents[100] ^= 1
    if damage == 'truncated': contents = contents[:30]
    encrypted.write_bytes(contents)
    with pytest.raises((ValueError, InvalidTag)):
        transform(encrypted, output, 'wrong-password' if damage == 'password' else CONFIG['backup_password'], decrypt=True)
    assert not output.exists()
    assert not list(tmp_path.glob('.airlink-backup-*'))


def test_config_encrypted_secrets_preserved_and_never_returned(worker):
    result = worker.configure(CONFIG)
    assert result['has_client_secret'] and result['has_backup_password']
    for secret in (CONFIG['client_secret'], CONFIG['backup_password']):
        assert secret not in json.dumps(result)
        assert secret.encode() not in (cloud.ROOT/'settings.enc').read_bytes()
    assert (cloud.ROOT/'settings.enc').stat().st_mode & 0o777 == 0o600
    assert (cloud.ROOT/'settings.key').stat().st_mode & 0o777 == 0o600
    worker.configure({**CONFIG, 'client_secret': '', 'backup_password': None, 'weekday': 2})
    assert cloud.configuration()['backup_password'] == CONFIG['backup_password']
    assert cloud.configuration()['client_secret'] == CONFIG['client_secret']
    assert worker.status()['weekday'] == 2
    connected(worker)
    worker.configure({**CONFIG, 'client_secret': 'replacement-secret'})
    assert not worker.status()['connected']
    worker.running = True
    with pytest.raises(ValueError, match='running'): worker.configure(CONFIG)


@pytest.mark.parametrize('uri', ['http://airlink.example.com', 'https://185.206.82.100',
    'https://bad..example.com', 'https://evil@airlink.example.com', 'https://bad_domain.example.com',
    'https://airlink.example.com:bad', 'https://airlink.example.com:99999'])
def test_invalid_redirect_rejected(uri):
    with pytest.raises(ValueError): cloud.redirect_uri(uri+cloud.CALLBACK)


def test_redirect_loopback_and_domain():
    for origin in ('http://localhost:18080', 'http://127.0.0.1:18080', 'https://airlink.example.com'):
        assert cloud.redirect_uri(origin+cloud.CALLBACK) == origin+cloud.CALLBACK
    with pytest.raises(ValueError): cloud.redirect_uri(CONFIG['redirect_uri']+'?anything=1')


@pytest.mark.parametrize('moment,expected', [
    ('2026-11-09T12:00:00+00:00', '2026-11-15T01:00:00+00:00'),
    ('2026-11-15T01:00:00+00:00', '2026-11-22T01:00:00+00:00'),
    ('2026-07-06T12:00:00+00:00', '2026-07-12T00:00:00+00:00'),
])
def test_weekly_schedule_uses_selected_timezone(moment, expected):
    assert cloud.next_run(CONFIG, datetime.fromisoformat(moment)) == expected


def test_background_scheduler_runs_without_web_requests(worker, monkeypatch):
    connected(worker)
    cloud.save_state({'next_run_at': '2026-01-01T00:00:00+00:00'})
    called = threading.Event()
    monkeypatch.setattr(worker, 'queue', lambda scheduled=False: called.set() if scheduled else None)
    worker.start()
    assert called.wait(2)
    worker.stop()
    called.clear()
    config = cloud.configuration(); config['automatic_enabled'] = False; cloud.save_config(config)
    worker.tick(); assert not called.is_set()
    config['automatic_enabled'] = True; config.pop('refresh_token'); cloud.save_config(config)
    worker.tick(); assert not called.is_set()


def test_queue_advances_due_date_once_but_manual_preserves_it(worker, monkeypatch):
    connected(worker)
    threads = []
    monkeypatch.setattr(cloud.threading, 'Thread', lambda **kw: SimpleNamespace(start=lambda: threads.append(kw)))
    old = '2026-01-01T00:00:00+00:00'
    cloud.save_state({'next_run_at': old})
    result = worker.queue()
    assert result['state']['next_run_at'] == old and result['running']
    with pytest.raises(ValueError, match='running'): worker.queue()
    worker.running = False
    worker.tick()
    assert datetime.fromisoformat(cloud.state()['next_run_at']) > datetime.now(timezone.utc)
    worker.running = False
    worker.tick()
    assert len(threads) == 2


def test_worker_start_failure_does_not_stick_running(worker, monkeypatch):
    connected(worker)
    def fail(): raise RuntimeError('thread unavailable')
    monkeypatch.setattr(cloud.threading, 'Thread', lambda **kw: SimpleNamespace(start=fail))
    with pytest.raises(ValueError, match='Cannot start'): worker.queue()
    assert not worker.running and cloud.state()['status'] == 'failed'


def test_oauth_bound_to_owner_state_and_single_use(worker, monkeypatch):
    worker.configure(CONFIG)
    with pytest.raises(ValueError, match='HTTPS domain'):
        worker.authorize('owner1', 'http://localhost'+cloud.CALLBACK)
    start = worker.authorize('owner1', CONFIG['redirect_uri'])
    params = parse_qs(urlsplit(start['authorization_url']).query)
    assert params['scope'] == [drive.SCOPE]
    assert params['access_type'] == ['offline'] and params['code_challenge_method'] == ['S256']
    assert start['state'] not in (cloud.ROOT/'settings.enc').read_text()
    calls = []
    def token(config, **kw):
        calls.append(kw)
        return {'refresh_token': 'private-refresh', 'access_token': 'private-access', 'scope': drive.SCOPE}
    monkeypatch.setattr(drive, 'token', token)
    monkeypatch.setattr(drive, 'account', lambda _: 'owner@example.com')
    monkeypatch.setattr(drive, 'folder', lambda *a: 'folder123')
    for owner_id, nonce in [('wrong-owner', start['state']), ('owner1', 'wrong-state')]:
        with pytest.raises(ValueError, match='expired'): worker.complete(owner_id, nonce, 'private-code')
    assert not calls
    result = worker.complete('owner1', start['state'], 'private-code')
    assert result['connected'] and len(calls[0]['verifier']) >= 43
    assert 'private-refresh' not in json.dumps(result)
    with pytest.raises(ValueError, match='expired'): worker.complete('owner1', start['state'], 'private-code')
    assert len(calls) == 1


def test_expired_oauth_cannot_exchange_code(worker, monkeypatch):
    worker.configure(CONFIG)
    start = worker.authorize('owner', CONFIG['redirect_uri'])
    config = cloud.configuration(); config['pending']['expires'] = 0; cloud.save_config(config)
    monkeypatch.setattr(drive, 'token', lambda *a, **kw: pytest.fail('must not exchange expired code'))
    with pytest.raises(ValueError, match='expired'): worker.complete('owner', start['state'], 'code')


def test_disconnect_removes_tokens_keeps_password_and_backups(worker, monkeypatch):
    connected(worker)
    cloud.save_state({'last_success_at': 'previous', 'next_run_at': 'future'})
    monkeypatch.setattr(drive, 'request', lambda *a, **kw: (503, {}, {}))
    result = worker.disconnect()
    assert not result['connected'] and not result['automatic_enabled']
    assert result['state']['next_run_at'] is None and result['state']['last_success_at'] == 'previous'
    assert result['has_backup_password'] and 'notice' in result
    assert 'refresh_token' not in cloud.configuration()


def local_backup(monkeypatch):
    source = cloud.BACKUPS/'20261109T120000Z-1234'; source.mkdir(parents=True)
    sums = []
    for name in ('database.dump', 'configuration.tar.gz'):
        content = ('private-'+name).encode(); (source/name).write_bytes(content)
        sums.append(hashlib.sha256(content).hexdigest()+'  '+name)
    (source/'SHA256SUMS').write_text('\n'.join(sums)+'\n')
    monkeypatch.setattr(cloud.subprocess, 'run', lambda *a, **kw: SimpleNamespace(returncode=0, stdout=str(source)+'\n'))
    return source


def test_end_to_end_local_backup_encrypt_upload_and_recover(worker, monkeypatch, tmp_path):
    config = connected(worker)
    source = local_backup(monkeypatch)
    monkeypatch.setattr(cloud, 'maintenance', nullcontext)
    monkeypatch.setattr(drive, 'token', lambda _: {'access_token': 'test-token'})
    monkeypatch.setattr(drive, 'folder', lambda *a: 'folder123')
    def upload(token, folder, path, progress):
        assert token == 'test-token' and folder == 'folder123'
        recovered = tmp_path/'recovered.tar'
        transform(path, recovered, CONFIG['backup_password'], decrypt=True)
        with tarfile.open(recovered) as archive:
            assert archive.getnames() == ['database.dump', 'configuration.tar.gz', 'SHA256SUMS']
            for name in archive.getnames():
                assert archive.extractfile(name).read() == (source/name).read_bytes()
        progress(path.stat().st_size, path.stat().st_size)
        return {'file_id': 'backup123', 'filename': path.name, 'file_url': 'https://drive.google.com/file/d/backup123/view'}
    monkeypatch.setattr(drive, 'upload', upload)
    worker.running = True; cloud.save_state({'started_at': cloud.stamp()})
    worker.run_backup(config)
    result = worker.status()
    assert result['state']['status'] == 'completed' and result['state']['last_success_at']
    assert result['state']['history'][0]['backup']['file_id'] == 'backup123'
    assert not result['running'] and not list(cloud.ROOT.glob('work-*'))
    assert source.exists()  # Never delete the local recovery copy.


def test_bad_backup_checksum_cannot_be_uploaded(worker, monkeypatch, tmp_path):
    config = connected(worker); source = local_backup(monkeypatch)
    (source/'database.dump').write_bytes(b'corrupted')
    monkeypatch.setattr(cloud, 'maintenance', nullcontext)
    monkeypatch.setattr(drive, 'upload', lambda *a: pytest.fail('must not upload a corrupt backup'))
    cloud.save_state({'last_success_at': 'previous-success'})
    worker.running = True; worker.run_backup(config)
    result = worker.status()
    assert result['state']['status'] == 'failed'
    assert result['state']['last_success_at'] == 'previous-success'
    assert 'checksum' in result['state']['error']
    assert not result['running'] and 'backup' not in result['state']['history'][0]


def test_update_lock_blocks_backup(worker, monkeypatch, tmp_path):
    import fcntl
    monkeypatch.setattr(cloud.update, 'ROOT', tmp_path/'updates')
    cloud.update.ROOT.mkdir()
    with (cloud.update.ROOT/'lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(ValueError, match='maintenance'):
            with cloud.maintenance(): pytest.fail('must not start while update lock is held')


def test_google_upload_resumes_lost_response_and_verifies_contents(tmp_path, monkeypatch):
    content = b'x' * (256*1024+20); path = tmp_path/'encrypted'; path.write_bytes(content)
    monkeypatch.setattr(drive, 'CHUNK', 256*1024)
    calls, sent = [], []
    def request(method, url, **kw):
        calls.append((method, url, kw))
        if len(calls) == 1: return 200, {'location': drive.UPLOAD_URL+'?upload_id=test'}, {}
        if len(calls) == 2: raise drive.DriveError('network interrupted')
        if len(calls) == 3:
            assert kw['headers']['Content-Range'] == f'bytes */{len(content)}'
            return 308, {'range': 'bytes=0-262143'}, {}
        assert kw['data'] == content[262144:]
        return 200, {}, {'id': 'file123', 'size': str(len(content)), 'md5Checksum': hashlib.md5(content).hexdigest()}
    monkeypatch.setattr(drive, 'request', request)
    result = drive.upload('access', 'folder', path, lambda a, b: sent.append((a, b)))
    assert result['sha256'] == hashlib.sha256(content).hexdigest()
    assert sent[-1] == (len(content), len(content)) and len(calls) == 4


@pytest.mark.parametrize('failure', ['location', 'checksum', 'position'])
def test_upload_rejects_unverified_or_invalid_results(tmp_path, monkeypatch, failure):
    path = tmp_path/'encrypted'; path.write_bytes(b'private-encrypted-bytes')
    calls = []
    def request(method, url, **kw):
        calls.append(method)
        if len(calls) == 1:
            return 200, {'location': 'https://evil.example/upload' if failure == 'location' else drive.UPLOAD_URL+'?upload_id=test'}, {}
        if failure == 'position': return 308, {'range': 'bytes=0-999999'}, {}
        return 200, {}, {'id': 'file', 'size': str(path.stat().st_size), 'md5Checksum': 'invalid'}
    monkeypatch.setattr(drive, 'request', request)
    with pytest.raises(drive.DriveError): drive.upload('access', 'folder', path, lambda *a: None)
    if failure == 'location': assert len(calls) == 1


def test_oauth_refresh_validation_and_no_secret_error(monkeypatch):
    calls = []
    def request(*args, **kwargs):
        calls.append(kwargs)
        return 200, {}, {'access_token': 'secret\r\ninvalid'}
    monkeypatch.setattr(drive, 'request', request)
    with pytest.raises(drive.DriveError) as exc:
        drive.token({**CONFIG, 'refresh_token': 'refresh-token'})
    assert 'secret' not in str(exc.value)
    assert calls[0]['form']['grant_type'] == 'refresh_token'


@pytest.mark.parametrize('url', ['https://evil.example/drive/v3/files', 'http://www.googleapis.com/drive/v3/files',
    'https://www.googleapis.com:444/drive/v3/files', 'https://user@www.googleapis.com/drive/v3/files'])
def test_google_http_client_rejects_other_destinations(url):
    with pytest.raises(drive.DriveError): drive.request('POST', url, headers={'Authorization': 'Bearer private'})


def test_owner_routes_and_audit_never_include_secrets(client, owner, worker, monkeypatch):
    calls = []
    def broker(action, payload):
        calls.append((action, payload))
        return worker.action(action.removeprefix('backups.google-drive.'), payload)
    monkeypatch.setattr(api, 'broker', broker)
    response = client.put('/api/backups/google-drive', headers=owner, json=CONFIG)
    assert response.status_code == 200, response.text
    assert CONFIG['backup_password'] not in response.text
    assert client.get('/api/backups/google-drive', headers=owner).status_code == 200
    own_id = client.get('/api/auth/me', headers=owner).json()['id']
    # Local test origin must match the registered callback exactly.
    cloud.save_config({**cloud.configuration(), 'redirect_uri': 'http://testserver'+cloud.CALLBACK})
    response = client.post('/api/backups/google-drive/authorize', headers=owner)
    assert response.status_code == 200, response.text
    assert calls[-1][1]['owner_id'] == own_id
    response = client.put('/api/backups/google-drive', headers=owner, json={**CONFIG, 'backup_password': 'private-'*200})
    assert response.status_code == 422 and 'private-' not in response.text
    with SessionLocal() as db:
        logs = db.query(AuditLog).all()
        assert any(log.action == 'backup.google_drive.configure' for log in logs)
        assert CONFIG['client_secret'] not in str([log.__dict__ for log in logs])
        assert CONFIG['backup_password'] not in str([log.__dict__ for log in logs])


def test_managers_cannot_access_backups_even_with_all_sections(client, owner, monkeypatch):
    mid, manager = user(client, owner, 'manager'); grant(client, owner, mid, list(ASSIGNABLE))
    monkeypatch.setattr(api, 'broker', lambda *a: pytest.fail('manager must not reach controller'))
    for method, suffix, body in [('GET','',None), ('PUT','',CONFIG), ('POST','/authorize',None),
        ('POST','/complete',{'state':'s'*32,'code':'private'}), ('POST','/run',None), ('POST','/disconnect',None)]:
        assert client.request(method, '/api/backups/google-drive'+suffix, headers=manager, json=body).status_code == 403
    client.cookies.clear()
    assert client.get('/api/backups/google-drive').status_code == 401


def test_callback_is_static_public_no_reflected_code_or_actions(client, monkeypatch):
    monkeypatch.setattr(api, 'broker', lambda *a: pytest.fail('callback must not mutate settings'))
    response = client.get(cloud.CALLBACK+'?code=private-code&state=private-state')
    assert response.status_code == 200
    assert 'private-code' not in response.text and 'private-state' not in response.text
    assert 'postMessage' in response.text and 'window.location.origin' in response.text
    assert "default-src 'none'" in response.headers['content-security-policy']
    assert response.headers['referrer-policy'] == 'no-referrer'
