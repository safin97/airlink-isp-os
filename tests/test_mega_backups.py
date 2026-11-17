from contextlib import nullcontext
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import tarfile
import threading
import time
from types import SimpleNamespace

import pytest
from airlink import api
from airlink.db import SessionLocal
from airlink.models import AuditLog
from cloud_backups import mega, mega_service
from recovery.cloud_archive import transform
from test_api import user

CONFIG = {'email': 'owner@example.com', 'account_password': 'private-account-password',
          'backup_password': 'private-backup-password', 'folder': 'AirLink Backups/Weekly',
          'automatic_enabled': True, 'weekday': 6, 'time': '02:00', 'timezone': 'Europe/Zurich'}


@pytest.fixture
def service(tmp_path, monkeypatch):
    def archive(path): path.write_bytes(b'private-database-and-config')
    worker = mega_service.MegaBackupService(tmp_path/'mega', archive=archive)
    monkeypatch.setattr(mega, 'binary', lambda: '/usr/bin/rclone')
    monkeypatch.setattr(mega, 'check_connection', lambda *args: None)
    yield worker
    worker.stop()


def connect(service):
    service.configure(CONFIG)
    service.test_connection()


def wait(service):
    deadline = time.monotonic() + 10
    while service.running and time.monotonic() < deadline:
        time.sleep(.01)
    assert not service.running


def test_secrets_encrypted_preserved_and_connection_rechecked(service):
    result = service.configure(CONFIG)
    assert not result['connected'] and result['state']['next_run_at'] is None
    assert result['has_account_password'] and result['has_backup_password']
    for key in ('account_password', 'backup_password'):
        assert CONFIG[key] not in json.dumps(result)
        assert CONFIG[key].encode() not in (service.root/'settings.enc').read_bytes()
    assert (service.root/'settings.enc').stat().st_mode & 0o777 == 0o600
    assert (service.root/'settings.key').stat().st_mode & 0o777 == 0o600
    service.test_connection()
    previous = service.state()['next_run_at']
    result = service.configure({**CONFIG, 'account_password': None, 'backup_password': None})
    assert result['connected'] and result['state']['next_run_at'] == previous
    assert service.config()['account_password'] == CONFIG['account_password']
    result = service.configure({**CONFIG, 'account_password': 'replacement-password'})
    assert not result['connected'] and result['state']['next_run_at'] is None


@pytest.mark.parametrize('change', [
    {'email': 'inject\n[remote]\ntype=local'}, {'email': 'new@example.com', 'account_password': None},
    {'account_password': 'secret\nextra'}, {'account_password': 'secret\x00extra'},
    {'folder': '../unsafe'}, {'folder': '/absolute'}, {'folder': 'remote:other'},
    {'folder': 'folder//nested'}, {'folder': 'folder\npass = wrong'},
    {'backup_password': 'short'}, {'weekday': True}, {'weekday': 7},
    {'time': '25:00'}, {'timezone': 'Not/AZone'}, {'automatic_enabled': 'true'},
])
def test_bad_configuration_rejected_without_changing_saved_settings(service, change):
    connect(service)
    before = service.config()
    with pytest.raises(ValueError): service.configure({**CONFIG, **change})
    assert service.config() == before


def test_connection_failure_does_not_enable_weekly_jobs(service, monkeypatch):
    connect(service)
    def fail(*args): raise mega.MegaError('Safe connection failure')
    monkeypatch.setattr(mega, 'check_connection', fail)
    with pytest.raises(mega.MegaError): service.test_connection()
    assert not service.status()['connected'] and not service.testing
    assert service.state()['next_run_at'] is None
    with pytest.raises(ValueError, match='test'): service.queue()


def test_encrypted_upload_verified_before_success_and_plaintext_removed(service, monkeypatch, tmp_path):
    connect(service)
    def upload(config, path, root, progress):
        assert list(path.parent.iterdir()) == [path]
        assert not (path.parent.parent/'backup.tar').exists()
        assert b'private-database' not in path.read_bytes()
        recovered = tmp_path/'recovered.tar'
        transform(path, recovered, CONFIG['backup_password'], decrypt=True)
        assert recovered.read_bytes() == b'private-database-and-config'
        progress(status='verifying')
        assert service.state()['status'] == 'verifying'
        assert not service.state().get('last_success_at')
        return {'filename': path.name, 'remote_path': CONFIG['folder']+'/'+path.name,
                'size': path.stat().st_size, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    monkeypatch.setattr(mega, 'upload', upload)
    scheduled = service.state()['next_run_at']
    service.queue(); wait(service)
    state = service.state()
    assert state['status'] == 'completed' and state['last_success_at']
    assert state['next_run_at'] == scheduled  # Manual backup doesn't postpone weekly backup.
    assert state['history'][0]['backup']['sha256']
    assert not list(service.root.glob('work-*'))


def test_failed_upload_preserves_last_success_and_redacts_details(service, monkeypatch):
    connect(service)
    service.progress(last_success_at='previous-success', last_backup={'filename': 'older'})
    def fail(*args): raise RuntimeError('private-credential-should-not-leak')
    monkeypatch.setattr(mega, 'upload', fail)
    service.queue(); wait(service)
    state = service.state()
    assert state['status'] == 'failed' and state['last_success_at'] == 'previous-success'
    assert state['last_backup']['filename'] == 'older'
    assert 'private-credential' not in json.dumps(state)
    assert 'backup' not in state['history'][0]
    assert not list(service.root.glob('work-*'))


def test_weekly_scheduler_catches_up_once_without_browser(service, monkeypatch):
    connect(service)
    service.progress(next_run_at='2020-01-01T00:00:00+00:00')
    launched = []
    monkeypatch.setattr(mega_service.threading, 'Thread', lambda **kw: SimpleNamespace(start=lambda: launched.append(kw)))
    service.tick()
    assert service.running and len(launched) == 1
    assert datetime.fromisoformat(service.state()['next_run_at']) > datetime.now(timezone.utc)
    service.tick(); assert len(launched) == 1
    service.running = False
    service.tick(); assert len(launched) == 1
    service.configure({**CONFIG, 'automatic_enabled': False})
    service.progress(next_run_at='2020-01-01T00:00:00+00:00')
    service.tick(); assert len(launched) == 1


def test_timer_and_restart_recovery(service, monkeypatch):
    connect(service)
    service.progress(status='uploading', next_run_at='2020-01-01T00:00:00+00:00')
    abandoned = service.root/'work-abandoned'; abandoned.mkdir(); (abandoned/'backup.tar').write_bytes(b'secret')
    connection = service.root/'connection-abandoned'; connection.mkdir()
    called = threading.Event()
    monkeypatch.setattr(service, 'queue', lambda scheduled=False: called.set() if scheduled else None)
    service.start()
    assert called.wait(2)
    service.stop()
    assert service.state()['status'] == 'failed'
    assert not abandoned.exists() and not connection.exists()
    # Configuration and the weekly deadline survive new worker instances.
    reloaded = mega_service.MegaBackupService(service.root, archive=lambda p: None)
    assert reloaded.config()['verified'] and reloaded.state()['next_run_at']


def test_disconnect_stops_schedule_without_removing_cloud_history(service):
    connect(service)
    service.progress(last_success_at='previous', history=[{'status': 'completed'}])
    result = service.disconnect()
    assert not result['connected'] and not result['automatic_enabled']
    assert not result['has_account_password'] and result['has_backup_password']
    assert result['state']['next_run_at'] is None and result['state']['last_success_at'] == 'previous'
    assert len(result['state']['history']) == 1


def test_busy_and_thread_failure(service, monkeypatch):
    connect(service)
    service.running = True
    for action in (lambda: service.configure(CONFIG), service.queue, service.disconnect, service.test_connection):
        with pytest.raises(ValueError, match='finish'): action()
    service.running = False
    def fail(): raise RuntimeError('cannot start thread')
    monkeypatch.setattr(mega_service.threading, 'Thread', lambda **kw: SimpleNamespace(start=fail))
    with pytest.raises(ValueError, match='Cannot start'): service.queue()
    assert not service.running and service.state()['status'] == 'failed'


def test_missing_transfer_support_never_reports_upload_success(service, monkeypatch):
    connect(service)
    monkeypatch.setattr(mega, 'binary', lambda: None)
    assert not service.status()['supported']
    with pytest.raises(ValueError, match='transfer support'): service.queue()
    assert not service.running


def test_transport_keeps_credentials_out_of_argv_and_config_is_private(tmp_path, monkeypatch):
    monkeypatch.setattr(mega, 'binary', lambda: '/usr/bin/rclone')
    monkeypatch.setattr(mega.time, 'sleep', lambda _: None)
    monkeypatch.setenv('RCLONE_CONFIG_AIRLINKMEGA_TYPE', 'local')
    calls = []
    def run(args, **kwargs):
        calls.append(args)
        assert CONFIG['account_password'] not in str(args)
        assert not any(key.startswith('RCLONE_') for key in kwargs['env'])
        if args[1] == 'obscure':
            assert kwargs['input'] == CONFIG['account_password']+'\n'
            return SimpleNamespace(returncode=0, stdout='obscured-password\n')
        path = Path(args[args.index('--config')+1])
        assert path.stat().st_mode & 0o777 == 0o600
        contents = path.read_text()
        assert 'type = mega' in contents and 'use_https = true' in contents
        assert 'pass = obscured-password' in contents
        return SimpleNamespace(returncode=0, stdout='')
    monkeypatch.setattr(mega.subprocess, 'run', run)
    mega.check_connection(CONFIG, tmp_path)
    upload = tmp_path/'upload'; upload.mkdir(); path = upload/'backup.tar.airlink'; path.write_bytes(b'encrypted')
    states = []
    result = mega.upload(CONFIG, path, tmp_path, lambda **changes: states.append(changes['status']))
    assert result['sha256'] == hashlib.sha256(b'encrypted').hexdigest()
    assert states == ['uploading', 'verifying']
    assert [args[1] for args in calls] == ['obscure', 'mkdir', 'obscure', 'copyto', 'check']
    assert '--immutable' in calls[-2] and '--download' in calls[-1] and '--one-way' in calls[-1]
    assert not list(tmp_path.glob('connection-*'))


@pytest.mark.parametrize('failure', ['nonzero', 'timeout'])
def test_transport_errors_redacted(failure, monkeypatch):
    monkeypatch.setattr(mega, 'binary', lambda: '/usr/bin/rclone')
    def run(*args, **kwargs):
        if failure == 'timeout': raise subprocess.TimeoutExpired(['secret'], 10, output='secret')
        return SimpleNamespace(returncode=1, stdout='secret', stderr='secret')
    monkeypatch.setattr(mega.subprocess, 'run', run)
    with pytest.raises(mega.MegaError) as exc: mega.run(['mkdir', 'airlinkmega:folder'])
    assert 'secret' not in str(exc.value)


def test_verification_failure_never_returns_success(tmp_path, monkeypatch):
    monkeypatch.setattr(mega.time, 'sleep', lambda _: None)
    def run(args, **kwargs):
        if args[0] == 'obscure': return 'obscured'
        if args[0] == 'check': raise mega.MegaError('Remote bytes differ')
        return ''
    monkeypatch.setattr(mega, 'run', run)
    upload = tmp_path/'upload'; upload.mkdir(); path = upload/'backup'; path.write_bytes(b'encrypted')
    with pytest.raises(mega.MegaError): mega.upload(CONFIG, path, tmp_path, lambda **kw: None)
    assert not list(tmp_path.glob('connection-*'))


def test_owner_routes_and_no_secrets_in_validation_or_audit(client, owner, service, monkeypatch):
    calls = []
    def broker(action, payload):
        calls.append(action)
        return service.action(action.removeprefix('backups.mega.'), payload)
    monkeypatch.setattr(api, 'broker', broker)
    assert client.put('/api/backups/mega', headers=owner, json=CONFIG).status_code == 200
    assert client.post('/api/backups/mega/test', headers=owner).json()['connected']
    result = client.get('/api/backups/mega', headers=owner)
    assert CONFIG['account_password'] not in result.text and CONFIG['backup_password'] not in result.text
    bad = client.put('/api/backups/mega', headers=owner, json={**CONFIG, 'account_password': 'private-'*200})
    assert bad.status_code == 422 and 'private-' not in bad.text
    with SessionLocal() as db:
        logs = db.query(AuditLog).all()
        assert any(log.action == 'backup.mega.configure' for log in logs)
        assert CONFIG['account_password'] not in str([log.__dict__ for log in logs])
    client.cookies.clear()
    assert client.get('/api/backups/mega').status_code == 401


@pytest.mark.parametrize('role', ['manager', 'technician', 'viewer'])
def test_nonowners_cannot_reach_mega_settings(client, owner, monkeypatch, role):
    _, headers = user(client, owner, role)
    monkeypatch.setattr(api, 'broker', lambda *args: pytest.fail('must not reach controller'))
    for method, suffix, body in [('GET', '', None), ('PUT', '', CONFIG),
                               ('POST', '/test', None), ('POST', '/run', None), ('POST', '/disconnect', None)]:
        assert client.request(method, '/api/backups/mega'+suffix, headers=headers,
                              **({'json': body} if body else {})).status_code == 403
