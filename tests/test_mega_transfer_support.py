import hashlib
import importlib.util
import io
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import zipfile

import pytest
from cloud_backups import mega, mega_service


def test_missing_backend_reports_installation_error_and_never_attempts_login(tmp_path, monkeypatch):
    binary = tmp_path/'rclone'; binary.write_bytes(b'incomplete build')
    monkeypatch.setattr(mega, 'binary', lambda: str(binary))
    mega._backend_available.cache_clear()
    calls = []
    def execute(args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=1, stdout='', stderr="didn't find backend called \"mega\"")
    monkeypatch.setattr(mega.subprocess, 'run', execute)
    service = mega_service.MegaBackupService(tmp_path/'settings', archive=lambda p: None)
    assert service.status()['transfer_available'] is False
    assert service.status()['supported'] is False
    assert len(calls) == 1  # Polling reuses an offline capability check.
    with pytest.raises(mega.MegaError, match='latest AirLink update'):
        mega.check_connection({'email': 'private@example.invalid', 'account_password': 'secret'}, tmp_path)
    assert len(calls) == 1 and calls[0][1:] == ['help', 'backend', 'mega']


def test_capability_cache_rechecks_replaced_binary(tmp_path, monkeypatch):
    binary = tmp_path/'rclone'; binary.write_bytes(b'old')
    monkeypatch.setattr(mega, 'binary', lambda: str(binary))
    mega._backend_available.cache_clear()
    calls = []
    def execute(args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=0 if binary.read_bytes()==b'official replacement' else 1,
                               stdout='Mega support', stderr='unavailable')
    monkeypatch.setattr(mega.subprocess, 'run', execute)
    assert not mega.backend_available()
    binary.write_bytes(b'official replacement')
    assert mega.backend_available() and mega.backend_available()
    assert len(calls) == 2


def test_missing_backend_error_is_specific_and_redacts_subprocess_output(monkeypatch):
    monkeypatch.setattr(mega, 'binary', lambda: '/fake/rclone')
    monkeypatch.setattr(mega.subprocess, 'run', lambda *a, **k: SimpleNamespace(returncode=1, stdout='private',
        stderr='Failed to create file system: didn\'t find filing system for "mega" private-account-data'))
    with pytest.raises(mega.MegaError, match='has no MEGA support') as error:
        mega.run(['mkdir','airlinkmega:Backups'])
    assert 'private' not in str(error.value) and 'Check your login' not in str(error.value)


@pytest.mark.parametrize('failure', [None, 'checksum', 'backend'])
def test_installer_verifies_checksum_and_backend_before_replacing_binary(tmp_path, monkeypatch, failure):
    path = Path(__file__).resolve().parents[1]/'scripts/install-backup-transfer.py'
    spec=importlib.util.spec_from_file_location('transfer_installer',path)
    installer=importlib.util.module_from_spec(spec); spec.loader.exec_module(installer)
    output=tmp_path/'tools'; output.mkdir(); (output/'rclone').write_bytes(b'previous')
    buffer=io.BytesIO()
    with zipfile.ZipFile(buffer,'w') as bundle:
        bundle.writestr('rclone-v1.76.0-linux-amd64/rclone',b'official test binary')
        bundle.writestr('rclone-v1.76.0-linux-amd64/README.txt',b'license and documentation')
    data=buffer.getvalue()
    monkeypatch.setattr(installer.platform,'system',lambda:'Linux')
    monkeypatch.setattr(installer.platform,'machine',lambda:'x86_64')
    monkeypatch.setattr(installer,'CHECKSUMS',{('linux','amd64'): '0'*64 if failure=='checksum' else hashlib.sha256(data).hexdigest()})
    monkeypatch.setattr(sys,'argv',['installer','--output',str(output)])
    probes=[]
    def execute(args, **kwargs):
        if args[0]=='curl':
            Path(args[args.index('--output')+1]).write_bytes(data)
            return SimpleNamespace(returncode=0)
        probes.append(args)
        assert args[1:]==['help','backend','mega']
        if failure=='backend': raise subprocess.CalledProcessError(1,args,stderr='no mega')
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(installer.subprocess,'run',execute)
    if failure:
        with pytest.raises(SystemExit): installer.main()
        assert (output/'rclone').read_bytes()==b'previous'
        assert not (output/'rclone.new').exists()
    else:
        installer.main()
        assert (output/'rclone').read_bytes()==b'official test binary'
        assert (output/'rclone-README.txt').read_bytes()==b'license and documentation'
    assert len(probes)==(0 if failure=='checksum' else 1)
