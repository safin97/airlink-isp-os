"""Run only inside a disposable AirLink Linux container, with networking disabled."""
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tarfile
import time

sys.path.insert(0, '/opt/airlink/os')
from cloud_backups import service as cloud
from recovery.cloud_archive import transform

assert os.geteuid() == 0 and Path('/.dockerenv').exists(), 'Disposable Docker QA only'

def run(command, **kwargs):
    return subprocess.run(command, check=True, capture_output=True, text=True, **kwargs).stdout.strip()

run(['pg_ctlcluster', '--skip-systemctl-redirect', '17', 'main', 'start'])
run(['runuser', '-u', 'postgres', '--', 'createdb', 'airlink'])
run(['runuser', '-u', 'postgres', '--', 'psql', '-d', 'airlink', '-c',
     "CREATE TABLE backup_probe(marker text); INSERT INTO backup_probe VALUES ('recovered-cloud-backup');"])
Path('/etc/airlink/qa-backup-secret').write_text('fixture-only-configuration')
Path('/etc/NetworkManager/system-connections').mkdir(parents=True, exist_ok=True)
config = dict(client_id='1234567890-qa.apps.googleusercontent.com', client_secret='fixture-client-secret',
              redirect_uri='https://airlink.example.com'+cloud.CALLBACK, folder_name='QA',
              backup_password='offline-recovery-test-password', automatic_enabled=False,
              weekday=6, time='02:00', timezone='UTC')
worker = cloud.BackupService()
worker.configure(config)
config = cloud.configuration()
config['refresh_token'] = 'fixture-refresh'
cloud.save_config(config)
cloud.drive.token = lambda _: {'access_token': 'fixture-access'}
cloud.drive.folder = lambda *a: 'fixture-folder'

def upload(token, folder, path, progress):
    recovered = Path('/tmp/recovered.tar')
    transform(path, recovered, config['backup_password'], decrypt=True)
    with tarfile.open(recovered) as bundle:
        assert set(bundle.getnames()) == {'database.dump', 'configuration.tar.gz', 'SHA256SUMS'}
        for member in bundle:
            assert member.isfile()
            Path('/tmp', member.name).write_bytes(bundle.extractfile(member).read())
    with tarfile.open('/tmp/configuration.tar.gz') as bundle:
        assert bundle.extractfile('etc/airlink/qa-backup-secret').read() == b'fixture-only-configuration'
        assert not any('google-drive-backup' in name for name in bundle.getnames())
    for line in Path('/tmp/SHA256SUMS').read_text().splitlines():
        digest, name = line.split()
        assert hashlib.sha256(Path('/tmp', name).read_bytes()).hexdigest() == digest
    progress(path.stat().st_size, path.stat().st_size)
    return {'file_id': 'fixture-file', 'filename': path.name, 'size': path.stat().st_size}

cloud.drive.upload = upload
worker.running = True
cloud.save_state({'started_at': cloud.stamp()})
worker.run_backup(config)
assert worker.status()['state']['status'] == 'completed', worker.status()['state']
assert not worker.running
run(['runuser', '-u', 'postgres', '--', 'createdb', 'airlink_recovery_qa'])
run(['runuser', '-u', 'postgres', '--', 'pg_restore', '--exit-on-error', '--single-transaction',
     '-d', 'airlink_recovery_qa', '/tmp/database.dump'])
assert run(['runuser', '-u', 'postgres', '--', 'psql', '-d', 'airlink_recovery_qa', '-Atc',
            'SELECT marker FROM backup_probe']) == 'recovered-cloud-backup'

# Use a new root controller process and its actual credential-checked Unix socket.
controller = subprocess.Popen(['/usr/bin/python3', '/opt/airlink/os/console/broker.py'],
                              stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
try:
    for _ in range(100):
        if Path('/run/airlink/control.sock').exists(): break
        assert controller.poll() is None
        time.sleep(.05)
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(10)
        connection.connect('/run/airlink/control.sock')
        connection.sendall(b'{"action":"backups.google-drive.status"}\n')
        result = json.loads(connection.makefile('rb').readline())
    assert result['ok'] and result['result']['state']['status'] == 'completed'
    assert 'fixture-refresh' not in json.dumps(result)
finally:
    controller.terminate(); controller.wait(timeout=10)
print('LINUX_BACKUP_ENCRYPT_DECRYPT_POSTGRES_RESTORE_CONTROLLER_OK')
