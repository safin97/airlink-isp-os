"""Signed update rehearsal; runs only in an explicitly identified disposable VM."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
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
    tower = client.post('/api/towers', json={'name': tower_name, 'location': 'Disposable QA VM'})
    tower.raise_for_status()
    tower_id = tower.json()['id']
    profile = client.post('/api/snmp-profiles', json={'name': profile_name,
        'username': 'release-lab', 'auth_key': 'Release-lab-auth-2026', 'priv_key': 'Release-lab-priv-2026'})
    profile.raise_for_status()
    profile_id = profile.json()['id']
    assert 'encrypted_credentials' not in profile.json()
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
    subprocess.run(['/usr/bin/python3', '/opt/airlink/os/updates/update.py', 'install'], check=True)
    assert update.read(update.ROOT / 'state.json', {})['status'] == 'installed'
    assert update.read(update.ROOT / 'installed.json', {})['sequence'] == sequence
    assert hashlib.sha256(Path('/etc/airlink/airlink.env').read_bytes()).hexdigest() == key_before
    login()
    assert any(t['id'] == tower_id and t['name'] == tower_name for t in get('/api/towers'))
    assert any(p['id'] == profile_id for p in get('/api/snmp-profiles'))
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
from sqlalchemy import select
from airlink.db import SessionLocal
from airlink.models import SNMPProfile
from airlink.security import cipher
with SessionLocal() as db:
    profile=db.get(SNMPProfile,os.environ["QA_PROFILE_ID"])
    data=json.loads(cipher().decrypt(profile.encrypted_credentials.encode()))
    assert data["username"]=="release-lab"
    assert data["auth_key"]=="Release-lab-auth-2026"
    assert data["priv_key"]=="Release-lab-priv-2026"
print("RELEASE_QA_ENCRYPTED_CREDENTIALS_PRESERVED")
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
