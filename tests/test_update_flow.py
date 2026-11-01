import base64
import json
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from updates import update


@pytest.fixture
def publisher(tmp_path, monkeypatch):
    root = tmp_path / 'updates'
    root.mkdir()
    monkeypatch.setattr(update, 'ROOT', root)
    monkeypatch.setattr(update, 'KEY', tmp_path / 'public.bin')
    monkeypatch.setattr(update, 'CONFIG', tmp_path / 'source.json')
    key = Ed25519PrivateKey.generate()
    update.KEY.write_bytes(key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw))
    update.CONFIG.write_text(json.dumps({'manifest_url': 'https://github.com/owner/repo/releases/latest/download/stable.json'}))
    meta = {'version': '0.2.0', 'sequence': 2, 'sha256': 'a' * 64, 'size': 100,
            'url': 'https://github.com/owner/repo/releases/download/v0.2.0/package.deb',
            'expires': (datetime.now(timezone.utc) + timedelta(days=30)).isoformat(),
            'release_notes': 'Test release', 'reboot_required': False}
    def publish(data=None):
        manifest = dict(meta if data is None else data)
        envelope = {'manifest': manifest, 'signature': base64.b64encode(key.sign(update.canonical(manifest))).decode()}
        def fetch(url, destination, limit, progress=None):
            destination.write_text(json.dumps(envelope))
        monkeypatch.setattr(update, 'download', fetch)
        return envelope
    return meta, publish


def test_check_current_release_is_up_to_date_but_install_replay_rejected(publisher):
    meta, publish = publisher
    publish()
    update.action('check', {})
    update.atomic(update.ROOT / 'installed.json', meta)
    assert update.action('check', {})['up_to_date'] is True
    assert update.status()['available'] is None
    assert update.status()['last_check']['up_to_date'] is True
    with pytest.raises(ValueError, match='replay/downgrade'):
        update.action('install', {})


def test_invalid_check_does_not_replace_trusted_manifest(publisher, monkeypatch):
    meta, publish = publisher
    envelope = publish()
    update.action('check', {})
    accepted = (update.ROOT / 'manifest.json').read_bytes()
    envelope['manifest']['sha256'] = 'b' * 64
    monkeypatch.setattr(update, 'download', lambda url, path, limit: path.write_text(json.dumps(envelope)))
    with pytest.raises(InvalidSignature):
        update.action('check', {})
    assert (update.ROOT / 'manifest.json').read_bytes() == accepted
    assert 'error' in update.status()['last_check']
    assert not (update.ROOT / 'candidate.json').exists()


def test_conflicting_same_sequence_and_lower_releases_rejected(publisher):
    meta, publish = publisher
    update.atomic(update.ROOT / 'installed.json', meta)
    publish({**meta, 'sha256': 'b' * 64})
    with pytest.raises(ValueError, match='conflicts'):
        update.action('check', {})
    publish({**meta, 'sequence': 1})
    with pytest.raises(ValueError, match='replay/downgrade'):
        update.action('check', {})


def test_release_is_pinned_for_all_mutating_actions(publisher, monkeypatch):
    meta, publish = publisher
    publish()
    update.action('check', {})
    def forbidden(*args, **kwargs):
        pytest.fail('Changed release must not download, verify or run commands')
    monkeypatch.setattr(update, 'download', forbidden)
    monkeypatch.setattr(update, 'verify_package', forbidden)
    monkeypatch.setattr(update.subprocess, 'run', forbidden)
    for action in ('download', 'verify', 'install', 'schedule'):
        with pytest.raises(ValueError, match='Release changed'):
            update.action(action, {'version': '0.1.0', 'sequence': 1})


def test_download_progress_and_failure_preserve_installation_state(publisher, monkeypatch):
    meta, publish = publisher
    publish()
    update.action('check', {})
    update.atomic(update.ROOT / 'state.json', {'status': 'failed', 'recovery_required': True})
    def download(url, path, limit, progress=None):
        progress(50, limit)
        assert update.status()['transfer']['received'] == 50
        path.write_bytes(b'x' * limit)
    monkeypatch.setattr(update, 'download', download)
    monkeypatch.setattr(update, 'verify_package', lambda meta: None)
    update.action('download', {'version': meta['version'], 'sequence': meta['sequence']})
    assert update.status()['transfer']['status'] == 'verified'
    assert update.status()['state']['status'] == 'failed'
    with pytest.raises(ValueError, match='local review'):
        update.action('install', {})
    def reject(meta):
        raise ValueError('Package digest mismatch')
    monkeypatch.setattr(update, 'verify_package', reject)
    with pytest.raises(ValueError, match='digest'):
        update.action('download', {})
    assert update.status()['transfer']['status'] == 'failed'
    assert update.status()['state']['recovery_required'] is True


def test_background_job_cannot_switch_release_after_owner_approval(publisher, monkeypatch):
    meta, publish = publisher
    publish()
    update.action('check', {})
    calls = []
    monkeypatch.setattr(update, 'verify_package', lambda meta: None)
    monkeypatch.setattr(update.subprocess, 'run', lambda command, **kwargs: calls.append(command))
    update.action('install', {'version': meta['version'], 'sequence': meta['sequence']})
    approved = update.read(update.ROOT / 'request.json', {})
    assert approved['sequence'] == 2 and approved['sha256'] == meta['sha256']
    assert len(calls) == 1
    publish({**meta, 'version': '0.3.0', 'sequence': 3})
    update.action('check', {})
    with pytest.raises(ValueError, match='changed after approval'):
        update.install()
    state = update.status()['state']
    assert state['status'] == 'rejected' and state['recovery_required'] is False
    assert len(calls) == 1  # No health command, stop, migration or install was run.
