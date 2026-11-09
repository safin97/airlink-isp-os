"""Signed update rehearsal; runs only in an explicitly identified disposable VM."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import traceback
import httpx

STAGE = Path('/var/lib/airlink-release-qa')


def main():
    if os.geteuid() != 0 or Path('/sys/class/dmi/id/sys_vendor').read_text().strip() != 'AirLinkReleaseQA':
        raise RuntimeError('Dedicated release QA virtual machine required')
    sys.path.insert(0, '/opt/airlink/os')
    from updates import update
    credentials = json.loads((STAGE / 'credentials.json').read_text())
    release = json.loads((STAGE / 'stable.json').read_text())['manifest']
    sequence = release['sequence']
    tower_name = f'Signed release preservation test {sequence}'
    profile_name = f'Release credential preservation test {sequence}'
    subprocess.run(['bash', '/opt/airlink/deployment/health.sh'], check=True)
    client = httpx.Client(base_url='http://127.0.0.1:8000', timeout=30)

    def login():
        response = client.post('/api/auth/login', json=credentials)
        response.raise_for_status()
        client.headers['Authorization'] = 'Bearer ' + response.json()['access_token']

    def get(path):
        result = client.get(path)
        result.raise_for_status()
        return result.json()

    login()
    starting_version = get('/api/health')['version']
    expected = STAGE / 'expected-version.txt'
    if expected.exists():
        assert starting_version == expected.read_text().strip(), starting_version
    print(f'RELEASE_QA_STARTING_VERSION={starting_version}', flush=True)
    tower = client.post('/api/towers', json={'name': tower_name, 'location': 'Disposable QA VM'})
    tower.raise_for_status()
    tower_id = tower.json()['id']
    profile = client.post('/api/snmp-profiles', json={'name': profile_name,
        'username': 'release-lab', 'auth_key': 'Release-lab-auth-2026', 'priv_key': 'Release-lab-priv-2026'})
    profile.raise_for_status()
    profile_id = profile.json()['id']
    assert 'encrypted_credentials' not in profile.json()
    device = client.post('/api/devices', json={'name': f'Release inventory preservation {sequence}',
        'tower_id': tower_id, 'ip_address': f'192.0.2.{sequence}', 'vendor': 'mikrotik',
        'snmp_profile_id': profile_id, 'poll_interval': 120, 'enabled': False})
    device.raise_for_status()
    device_id = device.json()['id']
    key_before = hashlib.sha256(Path('/etc/airlink/airlink.env').read_bytes()).hexdigest()
    prior_backups = set(Path('/var/backups/airlink').iterdir())
    for name in ('update-public-key.bin', 'update-source.json'):
        shutil.copyfile(STAGE / name, Path('/etc/airlink') / name)
    update.ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
    previous_sequence = update.read(update.ROOT / 'installed.json', {'sequence': 0})['sequence']
    assert sequence > previous_sequence
    shutil.copyfile(STAGE / 'stable.json', update.ROOT / 'manifest.json')
    packages = list(STAGE.glob('airlink-isp-os_*_amd64.deb'))
    assert len(packages) == 1
    shutil.copyfile(packages[0], update.ROOT / 'package.deb')
    meta = update.manifest()
    update.verify_package(meta)
    print('RELEASE_QA_PREINSTALL_SIGNATURE_AND_PACKAGE_OK', flush=True)
    # Exercise the same queued systemd job used by the dashboard.
    update.action('install', {'version': meta['version'], 'sequence': sequence})
    deadline = time.monotonic() + 900
    while time.monotonic() < deadline:
        state = update.read(update.ROOT / 'state.json', {})
        if state.get('status') == 'installed':
            break
        if state.get('status') in {'failed', 'rejected'}:
            raise RuntimeError(f'Release installation failed: {state}')
        time.sleep(2)
    else:
        raise RuntimeError('Timed out waiting for the queued update job')
    assert update.read(update.ROOT / 'state.json', {})['status'] == 'installed'
    assert update.read(update.ROOT / 'installed.json', {})['sequence'] == sequence
    assert hashlib.sha256(Path('/etc/airlink/airlink.env').read_bytes()).hexdigest() == key_before
    login()
    assert any(t['id'] == tower_id and t['name'] == tower_name for t in get('/api/towers'))
    assert any(p['id'] == profile_id for p in get('/api/snmp-profiles'))
    preserved_device = next(d for d in get('/api/devices') if d['id'] == device_id)
    assert preserved_device['poll_interval'] == 120 and preserved_device['enabled'] is False
    assert preserved_device['snmp_profile_id'] == profile_id
    assert preserved_device['connection_timeout'] == 2 and preserved_device['down_since'] is None
    print('RELEASE_QA_DEVICE_TIMING_MIGRATION_PRESERVED', flush=True)
    assert all(s == 'active' for s in get('/api/system')['services'].values())
    updates = get('/api/updates')
    assert updates['current_version'] == release['version']
    assert updates['state']['install_supported'] is True
    assert 'transfer' in updates['state']  # The long-lived controller reloaded the new code.
    new_backups = set(Path('/var/backups/airlink').iterdir()) - prior_backups
    assert new_backups
    for backup in new_backups:
        subprocess.run(['sha256sum', '-c', 'SHA256SUMS'], cwd=backup, check=True)
    env = dict(os.environ)
    for line in Path('/etc/airlink/airlink.env').read_text().splitlines():
        if '=' in line:
            key, value = line.split('=', 1)
            env[key] = value
    env['QA_PROFILE_ID'] = profile_id
    check = '''import json,os
from sqlalchemy import inspect, text
from alembic.config import Config
from alembic.script import ScriptDirectory
from airlink.db import Base, engine, SessionLocal
from airlink.models import SNMPProfile
from airlink.security import cipher
with SessionLocal() as db:
    profile=db.get(SNMPProfile,os.environ["QA_PROFILE_ID"])
    data=json.loads(cipher().decrypt(profile.encrypted_credentials.encode()))
    assert data["username"]=="release-lab"
    assert data["auth_key"]=="Release-lab-auth-2026"
    assert data["priv_key"]=="Release-lab-priv-2026"
    config=Config('/opt/airlink/database/alembic.ini')
    config.set_main_option('script_location','/opt/airlink/database')
    heads=set(ScriptDirectory.from_config(config).get_heads())
    assert set(db.execute(text('SELECT version_num FROM alembic_version')).scalars())==heads
    inspector=inspect(engine)
    for table in Base.metadata.sorted_tables:
        actual={column['name'] for column in inspector.get_columns(table.name)}
        assert set(table.columns.keys()) <= actual, table.name
print("RELEASE_QA_ENCRYPTED_CREDENTIALS_PRESERVED")
print("RELEASE_QA_MIGRATION_HEAD_AND_SCHEMA_OK")
'''
    subprocess.run(['runuser', '-u', 'airlink', '--preserve-environment', '--',
                    '/opt/airlink/venv/bin/python', '-c', check], env=env, check=True)
    try:
        update.manifest()
    except ValueError as exc:
        assert 'replay/downgrade' in str(exc)
    else:
        raise AssertionError('Installed update replay was accepted')
    branding = Path('/opt/airlink/os/branding/airlink-horizontal.png')
    if branding.exists():
        assert Path('/boot/grub/themes/airlink/airlink-horizontal.png').read_bytes() == branding.read_bytes()
        assert '/themes/airlink/theme.txt' in Path('/boot/grub/grub.cfg').read_text()
        print('RELEASE_QA_INSTALLED_BOOT_BRANDING_OK', flush=True)
    # The completed one-shot must not repeat destructive fixtures on a boot check.
    subprocess.run(['systemctl', 'disable', 'airlink-release-qa.service'], check=True)
    print('RELEASE_QA_INSTALL_DATA_BACKUP_SERVICES_REPLAY_OK', flush=True)
    (STAGE / 'passed').write_text('signed update install passed\n')


if __name__ == '__main__':
    try:
        main()
    except Exception:
        print('RELEASE_QA_FAILED', flush=True)
        traceback.print_exc()
        raise
