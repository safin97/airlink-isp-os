from datetime import datetime
import pytest
from cryptography.exceptions import InvalidTag
from cloud_backups import service as cloud
from recovery.cloud_archive import transform, CHUNK
CONFIG = {'backup_password': 'offline-recovery-password', 'weekday': 6, 'time': '02:00', 'timezone': 'Europe/Zurich'}


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


@pytest.mark.parametrize('moment,expected', [
    ('2026-11-09T12:00:00+00:00', '2026-11-15T01:00:00+00:00'),
    ('2026-11-15T01:00:00+00:00', '2026-11-22T01:00:00+00:00'),
    ('2026-07-06T12:00:00+00:00', '2026-07-12T00:00:00+00:00'),
])
def test_weekly_schedule_uses_selected_timezone(moment, expected):
    assert cloud.next_run(CONFIG, datetime.fromisoformat(moment)) == expected


def test_update_lock_blocks_backup(monkeypatch, tmp_path):
    import fcntl
    monkeypatch.setattr(cloud.update, 'ROOT', tmp_path/'updates')
    cloud.update.ROOT.mkdir()
    with (cloud.update.ROOT/'lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(ValueError, match='maintenance'):
            with cloud.maintenance(): pytest.fail('must not start while update lock is held')
