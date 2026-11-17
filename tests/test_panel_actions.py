import json
import pytest
from console import panel_actions as panel
from network import configure


def test_subnet_mask_and_dns_validation():
    data = panel.network_payload('eth0', 'static', '192.0.2.10', '255.255.255.0', '192.0.2.1', '1.1.1.1, 8.8.8.8', 'airlink')
    assert data['prefix'] == 24 and data['dns'] == ['1.1.1.1', '8.8.8.8']
    assert panel.network_payload('eth0', 'dhcp', '', '', '', '', 'airlink')['method'] == 'dhcp'
    with pytest.raises(ValueError, match='Subnet'):
        panel.network_payload('eth0', 'static', '192.0.2.10', '255.0.255.0', '192.0.2.1', '1.1.1.1', 'airlink')
    with pytest.raises(ValueError, match='Gateway'):
        panel.network_payload('eth0', 'static', '192.0.2.10', '24', '198.51.100.1', '1.1.1.1', 'airlink')


@pytest.mark.parametrize('role', ['viewer', 'manager', 'technician'])
def test_local_privileged_actions_recheck_owner(monkeypatch, role):
    monkeypatch.setattr(panel, 'api', lambda *args: {'role': role})
    monkeypatch.setattr(panel, 'run', lambda *args, **kwargs: pytest.fail('Unauthorized system command'))
    for action in ('settings', 'save_settings', 'backup', 'restore', 'restart_services', 'shutdown', 'logs', 'terminal'):
        with pytest.raises(panel.SessionExpired):
            panel.local_action(action, {'confirm': True}, 'token')


def test_time_validation_before_mutation(monkeypatch):
    monkeypatch.setattr(panel, 'timezones', lambda: ['UTC', 'Europe/Zurich'])
    good = {'hostname': 'airlink-office', 'timezone': 'Europe/Zurich', 'ntp': False, 'manual_time': '2026-11-01 12:34:56'}
    assert panel.validate_settings(good) == ('airlink-office', 'Europe/Zurich', False, '2026-11-01 12:34:56')
    for changed in ({'hostname': '--bad'}, {'timezone': '../etc/passwd'}, {'ntp': 'true'},
                    {'manual_time': '2026-02-31 12:00:00'}, {'ntp': True}):
        with pytest.raises(ValueError):
            panel.validate_settings(dict(good, **changed))


def test_backup_selection_excludes_symlinks(tmp_path, monkeypatch):
    monkeypatch.setattr(panel, 'BACKUPS', tmp_path)
    real = tmp_path / 'backup'; real.mkdir(); (real/'SHA256SUMS').write_text('test')
    (tmp_path/'escape').symlink_to(real)
    assert panel.backup_paths() == ['backup']


def test_settings_guard_against_running_update(tmp_path, monkeypatch):
    monkeypatch.setattr(panel, 'api', lambda *args: {'role': 'owner', 'id': 1})
    monkeypatch.setattr(panel.update, 'ROOT', tmp_path)
    (tmp_path/'state.json').write_text(json.dumps({'status': 'installing'}))
    monkeypatch.setattr(panel, 'run', lambda *args, **kwargs: pytest.fail('Changed settings during update'))
    with pytest.raises(ValueError, match='requires attention'):
        panel.local_action('save_settings', {'confirm': True}, 'token')


def test_network_duplicate_pending_apply_rejected(tmp_path, monkeypatch):
    pending = tmp_path/'pending.json'
    configure.write(pending, {'deadline': 99999999999})
    monkeypatch.setattr(configure, 'PENDING', pending)
    with pytest.raises(ValueError, match='pending network'):
        configure.action('apply', {})


def test_expired_session_cannot_execute_local_commands(monkeypatch):
    def expired(*args):
        raise panel.SessionExpired('expired')
    monkeypatch.setattr(panel, 'api', expired)
    monkeypatch.setattr(panel, 'run', lambda *args, **kwargs: pytest.fail('Expired session ran a command'))
    with pytest.raises(panel.SessionExpired):
        panel.local_action('save_settings', {'confirm': True}, 'expired-token')


def test_settings_commands_are_fixed_and_saved_hostname_follows(tmp_path, monkeypatch):
    monkeypatch.setattr(panel, 'api', lambda *args: {'role': 'owner', 'id': 1})
    monkeypatch.setattr(panel.update, 'ROOT', tmp_path/'updates')
    monkeypatch.setattr(panel.update, 'restart_status', lambda: {'pending': False})
    monkeypatch.setattr(panel, 'timezones', lambda: ['UTC', 'Europe/Zurich'])
    monkeypatch.setattr(panel, 'settings_status', lambda: {'can_ntp': False})
    monkeypatch.setattr(configure, 'PENDING', tmp_path/'pending.json')
    monkeypatch.setattr(configure, 'STATE', tmp_path/'network.json')
    configure.write(configure.STATE, {'hostname': 'before', 'method': 'dhcp', 'interface': 'eth0'})
    commands = []
    monkeypatch.setattr(panel, 'run', lambda args, **kwargs: commands.append(args) or '')
    panel.local_action('save_settings', {'confirm': True, 'hostname': 'airlink-office', 'timezone': 'Europe/Zurich',
                                       'ntp': False, 'manual_time': '2026-11-01 12:00:00'}, 'token')
    assert commands[:3] == [['timedatectl', 'set-timezone', 'Europe/Zurich'],
                           ['timedatectl', 'set-time', '2026-11-01 12:00:00'], ['hostnamectl', 'set-hostname', 'airlink-office']]
    assert json.loads(configure.STATE.read_text())['hostname'] == 'airlink-office'


def test_setting_hostname_during_pending_network_change_is_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(panel, 'api', lambda *args: {'role': 'owner'})
    monkeypatch.setattr(panel.update, 'ROOT', tmp_path/'updates')
    monkeypatch.setattr(panel.update, 'restart_status', lambda: {'pending': False})
    monkeypatch.setattr(configure, 'PENDING', tmp_path/'pending.json')
    configure.write(configure.PENDING, {'deadline': 99999999999})
    monkeypatch.setattr(panel, 'run', lambda *args, **kwargs: pytest.fail('Changed pending network hostname'))
    with pytest.raises(ValueError, match='pending network'):
        panel.local_action('save_settings', {'confirm': True}, 'token')


def test_panel_restore_inherits_maintenance_lock(tmp_path, monkeypatch):
    import fcntl
    import subprocess
    import sys
    monkeypatch.setattr(panel, 'api', lambda *args: {'role': 'owner', 'id': 'owner'})
    monkeypatch.setattr(panel.update, 'ROOT', tmp_path/'updates')
    monkeypatch.setattr(panel.update, 'restart_status', lambda: {'pending': False})
    monkeypatch.setattr(panel, 'BACKUPS', tmp_path/'backups')
    backup = panel.BACKUPS/'saved'; backup.mkdir(parents=True)
    (backup/'SHA256SUMS').write_text('test')
    executed = []
    def run(args, **kwargs):
        if args[0] == 'bash':
            executed.append(args)
            fd = int(kwargs['env']['AIRLINK_MAINTENANCE_FD'])
            assert kwargs['pass_fds'] == (fd,)
            # A child can use the inherited lock; a separate open cannot acquire it.
            child = subprocess.run([sys.executable, '-c',
                'import fcntl,os; fcntl.flock(int(os.environ["AIRLINK_MAINTENANCE_FD"]), fcntl.LOCK_EX|fcntl.LOCK_NB)'],
                env=kwargs['env'], pass_fds=kwargs['pass_fds'])
            assert child.returncode == 0
            with (panel.update.ROOT/'lock').open('w') as other:
                with pytest.raises(BlockingIOError): fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
        return 'Restored'
    monkeypatch.setattr(panel, 'run', run)
    assert 'Database restored' in panel.local_action('restore', {'confirm': True, 'backup': 'saved'}, 'owner-token')
    assert len(executed) == 1


@pytest.fixture
def terminal_setup(tmp_path, monkeypatch):
    monkeypatch.setattr(panel, 'api', lambda *args: {'role': 'owner', 'id': 'owner'})
    monkeypatch.setattr(panel.os, 'geteuid', lambda: 0)
    monkeypatch.setenv('DISPLAY', ':0')
    monkeypatch.setenv('XAUTHORITY', '/root/.Xauthority')
    monkeypatch.setattr(panel.update, 'ROOT', tmp_path)
    monkeypatch.setattr(panel.update, 'restart_status', lambda: {'pending': False})
    commands = []
    monkeypatch.setattr(panel, 'run', lambda args, **kw: commands.append((args, kw)) or '')
    monkeypatch.setattr(panel.subprocess, 'run', lambda args, **kw: commands.append((args, kw)))
    return commands


@pytest.mark.parametrize('state', ['idle', 'failed', 'installing'])
def test_terminal_can_review_failed_or_interrupted_update(terminal_setup, state):
    panel.update.atomic(panel.update.ROOT/'state.json', {'status': state})
    result = panel.local_action('terminal', {'confirm': True, 'command': 'ignored'}, 'owner-token')
    command = next(args for args, kw in terminal_setup if args[0] == '/usr/bin/systemd-run')
    assert command[-1] == '/opt/airlink/os/console/terminal.sh'
    assert 'ignored' not in command
    assert '--property=RuntimeMaxSec=900' in command
    assert '--property=BindsTo=airlink-console.service' in command
    assert '--property=KillMode=control-group' in command
    assert '--setenv=DISPLAY=:0' in command
    assert '--setenv=XAUTHORITY=/root/.Xauthority' in command
    assert any(args[:2] == ['/usr/bin/systemctl', 'stop'] for args, kw in terminal_setup)
    assert 'Sign in again' in result


def test_terminal_requires_confirmation(terminal_setup):
    with pytest.raises(ValueError, match='Confirm'):
        panel.local_action('terminal', {}, 'owner-token')
    assert not terminal_setup


@pytest.mark.parametrize('display', ['', 'localhost:10.0', '192.0.2.1:0'])
def test_terminal_requires_local_display(terminal_setup, monkeypatch, display):
    monkeypatch.setenv('DISPLAY', display)
    with pytest.raises(ValueError, match='PC screen'):
        panel.local_action('terminal', {'confirm': True}, 'owner-token')
    assert not terminal_setup


def test_terminal_rejects_expired_session(terminal_setup, monkeypatch):
    def expired(*args):
        raise panel.SessionExpired('expired')
    monkeypatch.setattr(panel, 'api', expired)
    with pytest.raises(panel.SessionExpired):
        panel.local_action('terminal', {'confirm': True}, 'expired')
    assert not terminal_setup


def test_terminal_waits_for_active_installer(terminal_setup):
    import fcntl
    with (panel.update.ROOT/'lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(ValueError, match='operation is running'):
            panel.local_action('terminal', {'confirm': True}, 'owner-token')
    assert not terminal_setup


@pytest.mark.parametrize('pending', ['queued', 'restart'])
def test_terminal_waits_for_queued_update_or_restart(terminal_setup, monkeypatch, pending):
    panel.update.atomic(panel.update.ROOT/'state.json', {'status': pending})
    monkeypatch.setattr(panel.update, 'restart_status', lambda: {'pending': pending == 'restart'})
    with pytest.raises(ValueError, match='pending'):
        panel.local_action('terminal', {'confirm': True}, 'owner-token')
    assert not terminal_setup


def test_terminal_retains_lock_and_cleans_up_after_timeout(terminal_setup, monkeypatch):
    import fcntl
    import subprocess
    def run(args, **kwargs):
        if args[0] == '/usr/bin/systemd-run':
            with (panel.update.ROOT/'lock').open('w') as lock:
                with pytest.raises(BlockingIOError):
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            raise subprocess.TimeoutExpired(args, kwargs['timeout'])
        return ''
    monkeypatch.setattr(panel, 'run', run)
    with pytest.raises(subprocess.TimeoutExpired):
        panel.local_action('terminal', {'confirm': True}, 'owner-token')
    assert any(args[:2] == ['/usr/bin/systemctl', 'stop'] for args, kw in terminal_setup)
    with (panel.update.ROOT/'lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
