import fcntl
import subprocess
import pytest
from updates import update

@pytest.fixture
def appliance(tmp_path, monkeypatch):
    monkeypatch.setattr(update, 'ROOT', tmp_path)
    boot = {'id': 'boot-before'}
    def status():
        return {'boot_id': boot['id'], 'pending': update.read(tmp_path/'restart.json', {}).get('boot_id') == boot['id']}
    monkeypatch.setattr(update, 'restart_status', status)
    calls = []
    monkeypatch.setattr(update.subprocess, 'run', lambda args, **kwargs: calls.append(args))
    return tmp_path, boot, calls

@pytest.mark.parametrize('payload', [{}, {'confirm': False}, {'confirm': 'true'}])
def test_restart_requires_explicit_confirmation(appliance, payload):
    with pytest.raises(ValueError, match='Confirm'):
        update.restart_system(payload)
    assert appliance[2] == []

@pytest.mark.parametrize('state', ['queued', 'installing', 'failed'])
def test_restart_rejects_active_or_failed_installation(appliance, state):
    update.atomic(appliance[0]/'state.json', {'status': state})
    with pytest.raises(ValueError, match='installation'):
        update.restart_system({'confirm': True})
    assert appliance[2] == []

def test_restart_lock_duplicate_and_new_boot(appliance):
    root, boot, calls = appliance
    with (root/'lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(ValueError, match='operation is active'):
            update.restart_system({'confirm': True})
    result = update.restart_system({'confirm': True})
    assert result['boot_id'] == 'boot-before'
    assert calls == [['systemd-run', '--unit=airlink-system-restart', '--on-active=5s', '/usr/bin/systemctl', 'reboot']]
    with pytest.raises(ValueError, match='already been requested'):
        update.restart_system({'confirm': True})
    # Even a previously scheduled installer cannot race the delayed restart.
    with pytest.raises(RuntimeError, match='restart is pending'):
        update.install()
    assert len(calls) == 1
    boot['id'] = 'boot-after'
    assert update.restart_status()['pending'] is False

def test_restart_command_failure_is_retryable(appliance, monkeypatch):
    def fail(*args, **kwargs):
        raise subprocess.CalledProcessError(1, 'systemd-run')
    monkeypatch.setattr(update.subprocess, 'run', fail)
    with pytest.raises(subprocess.CalledProcessError):
        update.restart_system({'confirm': True})
    assert not (appliance[0]/'restart.json').exists()

def test_queued_installer_waits_for_controller_lock(appliance, monkeypatch):
    import threading
    root, _, calls = appliance
    done = threading.Event()
    errors = []
    def no_package():
        raise ValueError('test has no package')
    monkeypatch.setattr(update, 'manifest', no_package)
    def worker():
        try: update.install()
        except Exception as exc: errors.append(exc)
        finally: done.set()
    with (root/'lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        assert not done.wait(0.1)
    assert done.wait(3)
    thread.join()
    assert len(errors) == 1 and isinstance(errors[0], ValueError)
    assert 'test has no package' in str(errors[0])
    assert calls == []
