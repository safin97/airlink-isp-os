import json
import stat
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.exceptions import InvalidSignature
from updates.github_release import configuration, init_key, prepare, repository
from updates.update import verify_manifest


@pytest.mark.parametrize('value', ['owner/airlink', 'https://github.com/owner/airlink',
                                   'https://github.com/owner/airlink.git/'])
def test_repository(value):
    assert repository(value) == 'owner/airlink'


@pytest.mark.parametrize('value', ['https://github.com.evil.test/owner/repo',
    'https://github.com/owner/repo?token=secret', 'https://user@github.com/owner/repo',
    'https://github.com/owner/repo/releases', 'owner/..', '../repo', 'owner/repo;cmd',
    'http://github.com/owner/repo', 'owner/repo#tag', 'git@github.com:owner/repo'])
def test_unexpected_repository_rejected(value):
    with pytest.raises(ValueError):
        repository(value)


def test_configuration_and_non_replacing_keys(tmp_path):
    public = init_key(tmp_path / 'keys')
    original = (tmp_path / 'keys/publisher-private.pem').read_bytes()
    assert stat.S_IMODE((tmp_path / 'keys/publisher-private.pem').stat().st_mode) == 0o600
    with pytest.raises(ValueError):
        init_key(tmp_path / 'keys')
    assert (tmp_path / 'keys/publisher-private.pem').read_bytes() == original
    out = tmp_path / 'config'
    configuration('owner/airlink', public, out)
    assert json.loads((out / 'update-source.json').read_text()) == {
        'manifest_url': 'https://github.com/owner/airlink/releases/latest/download/stable.json'}
    assert (out / 'update-public-key.bin').read_bytes() == public.read_bytes()
    assert len(list(out.iterdir())) == 2  # Never export the signing key with configuration.
    another = init_key(tmp_path / 'other-keys')
    with pytest.raises(ValueError):
        configuration('owner/airlink', another, out)
    assert (out / 'update-public-key.bin').read_bytes() == public.read_bytes()


def test_prepared_manifest_works_with_existing_updater(tmp_path):
    public = init_key(tmp_path / 'keys')
    package = tmp_path / 'fixture.deb'
    package.write_bytes(b'fixture payload; Debian package identity is checked by the appliance')
    notes = tmp_path / 'notes.md'
    notes.write_text('Release test')
    output = tmp_path / 'release'
    expires = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
    result = prepare('owner/airlink', tmp_path / 'keys/publisher-private.pem', package,
                     '0.2.0', 2, expires, notes, output)
    envelope = json.loads((output / 'stable.json').read_text())
    meta = verify_manifest(envelope, public.read_bytes(), current_sequence=1)
    assert result['tag'] == 'v0.2.0'
    assert meta['url'] == 'https://github.com/owner/airlink/releases/download/v0.2.0/airlink-isp-os_0.2.0_amd64.deb'
    assert (output / result['assets'][0]).read_bytes() == package.read_bytes()
    with pytest.raises(ValueError):
        verify_manifest(envelope, public.read_bytes(), current_sequence=2)
    envelope['manifest']['url'] = 'https://example.test/replaced.deb'
    with pytest.raises(InvalidSignature):
        verify_manifest(envelope, public.read_bytes())
    assert not list(output.glob('*.pem'))


def test_install_initial_source_is_idempotent_and_handles_partial_setup(tmp_path):
    from updates.install_source import install_source
    public = init_key(tmp_path / 'keys')
    source, destination = tmp_path / 'source', tmp_path / 'etc'
    configuration('safin97/airlink-isp-os', public, source)
    assert install_source(source, destination) == 'safin97/airlink-isp-os'
    first = {p.name: p.read_bytes() for p in destination.iterdir()}
    assert install_source(source, destination) == 'safin97/airlink-isp-os'
    assert first == {p.name: p.read_bytes() for p in destination.iterdir()}
    (destination / 'update-source.json').unlink()
    install_source(source, destination)
    assert first == {p.name: p.read_bytes() for p in destination.iterdir()}
    for path in destination.iterdir():
        assert stat.S_IMODE(path.stat().st_mode) == 0o644


def test_install_source_never_replaces_existing_trust(tmp_path):
    from updates.install_source import install_source
    public = init_key(tmp_path / 'keys')
    source, destination = tmp_path / 'source', tmp_path / 'etc'
    configuration('owner/original', public, source)
    install_source(source, destination)
    before = {p.name: p.read_bytes() for p in destination.iterdir()}
    another = init_key(tmp_path / 'other-keys')
    configuration('owner/new', another, tmp_path / 'replacement')
    with pytest.raises(ValueError, match='refusing to replace trust'):
        install_source(tmp_path / 'replacement', destination)
    assert before == {p.name: p.read_bytes() for p in destination.iterdir()}


def test_install_source_rejects_invalid_config_and_symlinks(tmp_path):
    from updates.install_source import install_source
    public = init_key(tmp_path / 'keys')
    source, destination = tmp_path / 'source', tmp_path / 'etc'
    configuration('owner/repo', public, source)
    destination.mkdir()
    (destination / 'update-public-key.bin').symlink_to(public)
    with pytest.raises(ValueError, match='symbolic-link'):
        install_source(source, destination)
    (destination / 'update-public-key.bin').unlink()
    (source / 'update-source.json').write_text(json.dumps({'manifest_url': 'http://example.test/stable.json'}))
    with pytest.raises(ValueError):
        install_source(source, destination)
    assert list(destination.iterdir()) == []
