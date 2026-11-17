import base64
import hashlib
import io
import json
import uuid
import zipfile
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from updates import update, local

USER = str(uuid.uuid4())


@pytest.fixture
def offline(tmp_path, monkeypatch):
    monkeypatch.setattr(update, 'ROOT', tmp_path / 'updates')
    update.ROOT.mkdir()
    monkeypatch.setattr(update, 'KEY', tmp_path / 'key')
    # Deliberately absent: offline updates must not require a working online source.
    monkeypatch.setattr(update, 'CONFIG', tmp_path / 'missing-source.json')
    key = Ed25519PrivateKey.generate()
    update.KEY.write_bytes(key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw))
    monkeypatch.setattr(local.shutil, 'disk_usage', lambda _: SimpleNamespace(free=10 * 1024**3))
    monkeypatch.setattr(update, 'download', lambda *a, **k: pytest.fail('Offline update attempted network access'))
    monkeypatch.setattr(update.subprocess, 'check_output', lambda *a, **k:
        'Package: airlink-isp-os\nArchitecture: amd64\nVersion: 0.2.0\n')
    commands = []
    monkeypatch.setattr(update.subprocess, 'run', lambda args, **kw: commands.append(args))
    package = b'Debian package fixture' * 2000
    meta = {'version': '0.2.0', 'sequence': 2, 'size': len(package), 'sha256': hashlib.sha256(package).hexdigest(),
            'url': 'https://example.invalid/update.deb', 'expires': (datetime.now(timezone.utc) + timedelta(days=10)).isoformat(),
            'release_notes': 'Offline release', 'reboot_required': False}
    def bundle(changes=None, payload=package, extra=None, tamper_signature=False):
        manifest = {**meta, **(changes or {})}
        envelope = {'manifest': manifest, 'signature': base64.b64encode(key.sign(update.canonical(manifest))).decode()}
        if tamper_signature:
            envelope['manifest']['version'] = '9.9.9'
        result = io.BytesIO()
        with zipfile.ZipFile(result, 'w') as archive:
            archive.writestr('manifest.json', json.dumps(envelope))
            archive.writestr('package.deb', payload)
            if extra:
                archive.writestr(extra, 'untrusted')
        return result.getvalue()
    return bundle, meta, commands


def call(name, payload=None, user=USER):
    return update.action('local.' + name, {**(payload or {}), 'user_id': user})


def upload(data):
    token = call('start', {'size': len(data)})['token']
    for offset in range(0, len(data), local.CHUNK):
        result = call('chunk', {'token': token, 'offset': offset, 'data': base64.b64encode(data[offset:offset + local.CHUNK]).decode()})
        assert result['received'] == min(offset + local.CHUNK, len(data))
    return token


def test_offline_upload_verify_confirm_uses_normal_installer(offline):
    bundle, meta, commands = offline
    assert update.status()['configured'] is False
    assert update.status()['local_update_supported'] is True
    token = upload(bundle())
    ready = call('finish', {'token': token})
    assert ready['release'] == meta
    assert not commands and not (update.ROOT / 'package.deb').exists()
    with pytest.raises(ValueError, match='confirm'):
        call('install', {'token': token})
    result = call('install', {'token': token, 'confirm': True, 'version': meta['version'], 'sequence': meta['sequence']})
    assert result['status'] == 'install'
    assert update.manifest() == meta
    update.verify_package(meta)
    assert update.read(update.ROOT / 'request.json', {})['sha256'] == meta['sha256']
    assert update.status()['state']['status'] == 'queued'
    assert commands == [['systemctl', 'start', '--no-block', 'airlink-update-job.service']]
    assert not (update.ROOT / 'local-upload').exists()


@pytest.mark.parametrize('fault', ['signature', 'digest', 'size', 'expired', 'replay', 'traversal', 'trust-key', 'truncated', 'identity'])
def test_invalid_bundles_never_replace_prepared_online_update(offline, monkeypatch, fault):
    bundle, meta, commands = offline
    (update.ROOT / 'package.deb').write_bytes(b'previous package')
    update.atomic(update.ROOT / 'manifest.json', {'previous': 'manifest'})
    if fault == 'signature': data = bundle(tamper_signature=True)
    elif fault == 'digest': data = bundle(payload=b'x' * meta['size'])
    elif fault == 'size': data = bundle(payload=b'short')
    elif fault == 'expired': data = bundle({'expires': '2000-01-01T00:00:00Z'})
    elif fault == 'replay':
        update.atomic(update.ROOT / 'installed.json', meta)
        data = bundle()
    elif fault == 'traversal': data = bundle(extra='../outside')
    elif fault == 'trust-key': data = bundle(extra='update-public-key.bin')
    elif fault == 'truncated': data = bundle()[:-30]
    else:
        monkeypatch.setattr(update.subprocess, 'check_output', lambda *a, **k: 'Package: other\nArchitecture: amd64\nVersion: 0.2.0\n')
        data = bundle()
    token = upload(data)
    with pytest.raises(ValueError): call('finish', {'token': token})
    with pytest.raises(ValueError): call('install', {'token': token, 'confirm': True, 'version': '0.2.0', 'sequence': 2})
    assert not commands
    assert (update.ROOT / 'package.deb').read_bytes() == b'previous package'
    assert update.read(update.ROOT / 'manifest.json', {}) == {'previous': 'manifest'}


def test_bound_chunks_user_binding_cancel_retry_and_expiry(offline, monkeypatch):
    bundle, _, _ = offline
    data = bundle()
    token = call('start', {'size': len(data)})['token']
    with pytest.raises(ValueError, match='incomplete'): call('finish', {'token': token})
    for payload in ({'offset': 1, 'data': 'YQ=='}, {'offset': 0, 'data': '!'},
                    {'offset': 0, 'data': base64.b64encode(b'x' * (local.CHUNK + 1)).decode()}):
        with pytest.raises(ValueError): call('chunk', {'token': token, **payload})
    other = str(uuid.uuid4())
    for name in ('chunk', 'finish', 'install', 'cancel'):
        with pytest.raises(ValueError, match='another user'): call(name, {'token': token}, user=other)
    with pytest.raises(ValueError, match='Another user'): call('start', {'size': len(data)}, user=other)
    call('cancel', {'token': token})
    assert not (update.ROOT / 'local-upload').exists()
    new_token = upload(data)
    with pytest.raises(ValueError): call('finish', {'token': token})
    monkeypatch.setattr(local.time, 'time', lambda: 9999999999)
    with pytest.raises(ValueError, match='expired'): call('finish', {'token': new_token})
    assert not (update.ROOT / 'local-upload').exists()


@pytest.mark.parametrize('state', ['queued', 'installing', 'failed'])
def test_installation_recovery_not_bypassed(offline, state):
    update.atomic(update.ROOT / 'state.json', {'status': state})
    with pytest.raises(ValueError, match='local review'): call('start', {'size': 100})


def test_rechecks_signature_and_sequence_at_confirmation(offline):
    bundle, meta, commands = offline
    token = upload(bundle())
    call('finish', {'token': token})
    update.atomic(update.ROOT / 'installed.json', meta)
    with pytest.raises(ValueError, match='older'):
        call('install', {'token': token, 'confirm': True, 'version': '0.2.0', 'sequence': 2})
    assert not commands


def test_api_permissions_and_identity_are_server_enforced(client, owner, monkeypatch):
    from airlink import api
    from test_api import user
    from test_section_access import grant, readonly_grant
    manager_id, manager = user(client, owner, 'manager')
    calls = []
    def broker(action, payload):
        calls.append((action, payload))
        return {'status': 'ok'}
    monkeypatch.setattr(api, 'broker', broker)
    for action in ('start', 'chunk', 'finish', 'install', 'cancel'):
        path = '/api/updates/local/' + action
        assert client.post(path, json={}).status_code in (401, 403)
        assert client.post(path, headers=manager, json={}).status_code == 403
    readonly_grant(client, owner, manager_id, ['software_updates'])
    assert client.post('/api/updates/local/start', headers=manager, json={}).status_code == 403
    assert not calls
    readonly_grant(client, owner, manager_id, ['software_updates'], ['software_updates'])
    assert client.post('/api/updates/local/start', headers=manager, json={'user_id': 'forged', 'size': 10}).status_code == 200
    assert calls[-1] == ('updates.local.start', {'user_id': manager_id, 'size': 10})
    grant(client, owner, manager_id, [])
    assert client.post('/api/updates/local/install', headers=manager, json={}).status_code == 403
