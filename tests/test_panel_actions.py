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
    for action in ('settings', 'save_settings', 'backup', 'restore', 'restart_services', 'shutdown', 'logs'):
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
