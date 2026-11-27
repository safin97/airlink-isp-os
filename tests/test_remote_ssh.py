import json
from types import SimpleNamespace
import pytest
from airlink import api
from airlink.db import SessionLocal
from airlink.models import User
from airlink.security import hasher
from fastapi import HTTPException
from console import remote_ssh as ssh
from conftest import PASSWORD

SSH_PASSWORD = PASSWORD
SSH_OWNER = {'owner_id': 'owner-1', 'owner_username': 'owner'}


def test_owner_reauthentication_and_password_redaction(client, owner, monkeypatch):
    calls = []
    monkeypatch.setattr(api, 'broker', lambda action, payload=None: calls.append((action, payload)) or {'port': 2742})
    assert client.get('/api/system/ssh').status_code == 401
    payload = {'owner_password': 'wrong', 'sources': ['192.168.1.0/24']}
    assert client.post('/api/system/ssh/enable', headers=owner, json=payload).status_code == 403
    assert not calls
    payload['owner_password'] = PASSWORD
    response = client.post('/api/system/ssh/enable', headers=owner, json=payload)
    assert response.status_code == 200
    assert calls[0][0] == 'ssh.enable'
    assert calls[0][1]['ssh_password'] == PASSWORD
    assert calls[0][1]['owner_id']
    assert calls[0][1]['owner_username'] == 'owner'
    assert calls[0][1]['sources'] == ['192.168.1.0/24']
    assert PASSWORD not in response.text and SSH_PASSWORD not in response.text
    invalid = client.post('/api/system/ssh/enable', headers=owner, json={**payload, 'sources': []})
    assert invalid.status_code == 422 and PASSWORD not in invalid.text and SSH_PASSWORD not in invalid.text
    separate = client.post('/api/system/ssh/enable', headers=owner,
                           json={**payload, 'ssh_password': 'Another-SSH-Password-583!'})
    assert separate.status_code == 422
    assert 'Another-SSH-Password-583!' not in separate.text


@pytest.mark.parametrize('role', ['manager', 'technician', 'viewer'])
def test_ssh_is_never_delegated(client, owner, monkeypatch, role):
    with SessionLocal() as db:
        db.add(User(username='ssh-other', role=role, password_hash=hasher.hash(PASSWORD)))
        db.commit()
    token = client.post('/api/auth/login', json={'username': 'ssh-other', 'password': PASSWORD}).json()['access_token']
    headers = {'Authorization': 'Bearer ' + token}
    monkeypatch.setattr(api, 'broker', lambda *a: pytest.fail('Non-owner reached SSH controller'))
    assert client.get('/api/system/ssh', headers=headers).status_code == 403
    for action in ('enable', 'disable', 'install'):
        body = {'owner_password': PASSWORD}
        if action == 'enable':
            body.update(sources=['192.168.1.0/24'])
        assert client.post('/api/system/ssh/' + action, headers=headers, json=body).status_code == 403


def test_sources_and_credentials_are_validated():
    assert ssh.sources(['192.168.1.7', '192.168.1.0/24', '2001:db8::1']) == ['192.168.1.0/24', '2001:db8::1/128']
    for value in ([], ['bad; flush ruleset'], ['127.0.0.1'], ['ff02::1'], ['192.168.1.1\naccept']):
        with pytest.raises(ValueError):
            ssh.sources(value)
    for value in ('short', 'x'*30, 'Password-with-newline\n123', 'abc1234567890\x00xyz'):
        with pytest.raises(ValueError):
            ssh.validate_password(value)


@pytest.fixture
def controller(monkeypatch, tmp_path):
    monkeypatch.setattr(ssh, 'ROOT', tmp_path / 'ssh')
    monkeypatch.setattr(ssh, 'CONFIG', tmp_path / 'etc/sshd_config')
    monkeypatch.setattr(ssh, 'SUDOERS', tmp_path / 'sudoers/airlink-remote')
    monkeypatch.setattr(ssh, 'HOME', tmp_path / 'remote-home')
    monkeypatch.setattr(ssh, 'SSHD', tmp_path / 'sshd')
    ssh.SSHD.touch()
    monkeypatch.setattr(ssh, 'installed', lambda: True)
    monkeypatch.setattr(ssh.os, 'geteuid', lambda: 0)
    monkeypatch.setattr(ssh.update, 'ROOT', tmp_path / 'updates')
    monkeypatch.setattr(ssh.pc, 'ROOT', tmp_path / 'pc-updates')
    monkeypatch.setattr(ssh.update, 'restart_status', lambda: {'pending': False})
    calls = []
    accounts = {}
    active = {'value': False}
    def account(name):
        if name not in accounts:
            raise KeyError(name)
        return accounts[name]
    monkeypatch.setattr(ssh.pwd, 'getpwnam', account)
    # The controller must not create /run/sshd on the development host.
    original_mkdir = ssh.Path.mkdir
    def mkdir(path, *args, **kwargs):
        if str(path) != '/run/sshd':
            return original_mkdir(path, *args, **kwargs)
    monkeypatch.setattr(ssh.Path, 'mkdir', mkdir)
    def run(args, **kwargs):
        calls.append((args, kwargs))
        if args[:2] == ['nft', '-j']:
            return json.dumps({'nftables': [
                {'chain': {'name': 'input'}}, {'chain': {'name': 'airlink_ssh'}},
                {'rule': {'chain': 'input', 'handle': 42, 'comment': 'AirLink SSH access'}},
            ]})
        if args[0] == 'useradd':
            ssh.HOME.mkdir()
            accounts[ssh.USER] = SimpleNamespace(pw_uid=1001)
        if args[:2] == ['systemctl', 'enable']:
            active['value'] = True
        if args[:2] == ['systemctl', 'disable']:
            active['value'] = False
        if args[:2] == ['systemctl', 'is-active']:
            return 'active' if active['value'] else 'inactive'
        return ''
    monkeypatch.setattr(ssh, 'run', run)
    return calls, accounts, active


def test_enable_and_disable_preserve_firewall_and_keep_password_out_of_arguments(controller):
    calls, accounts, active = controller
    result = ssh.action('enable', {**SSH_OWNER, 'sources': ['192.168.1.10'], 'ssh_password': SSH_PASSWORD})
    assert result['active'] and result['port'] == 2742 and result['username'] == 'airlink-admin'
    config = ssh.CONFIG.read_text()
    assert 'Port 2742\n' in config and 'PermitRootLogin no\n' in config
    assert 'AllowUsers airlink-admin\n' in config and 'DisableForwarding yes\n' in config
    assert SSH_PASSWORD not in ssh.CONFIG.read_text() + (ssh.ROOT / 'settings.json').read_text()
    password_calls = [(args, opts) for args, opts in calls if args == ['chpasswd']]
    assert password_calls[0][1]['secret'] == 'airlink-admin:' + SSH_PASSWORD + '\n'
    assert all(SSH_PASSWORD not in str(args) for args, opts in calls)
    scripts = [opts['secret'] for args, opts in calls if args[:2] == ['nft', '-f']]
    assert all('flush ruleset' not in script for script in scripts)
    assert 'ip saddr 192.168.1.10/32 accept' in scripts[-1]
    assert 'tcp dport 2742 jump airlink_ssh' in scripts[-1]
    assert 'ALL=(ALL:ALL) ALL' in ssh.SUDOERS.read_text()
    assert 'NOPASSWD' not in ssh.SUDOERS.read_text()
    assert ssh.HOME.stat().st_mode & 0o777 == 0o700
    result = ssh.action('disable', {})
    assert not result['enabled'] and not result['active']
    assert not ssh.SUDOERS.exists()
    assert any(args == ['usermod', '--lock', 'airlink-admin'] for args, opts in calls)


def test_unrelated_existing_linux_account_is_never_taken_over(controller):
    calls, accounts, active = controller
    accounts[ssh.USER] = SimpleNamespace(pw_uid=1002)
    with pytest.raises(ValueError, match='outside AirLink'):
        ssh.action('enable', {**SSH_OWNER, 'sources': ['192.168.1.10'], 'ssh_password': SSH_PASSWORD})
    assert not calls


def test_bad_configuration_fails_closed(controller, monkeypatch):
    calls, _, active = controller
    original = ssh.run
    def fail(args, **kwargs):
        if args[0] == str(ssh.SSHD):
            raise ValueError('Invalid sshd config')
        return original(args, **kwargs)
    monkeypatch.setattr(ssh, 'run', fail)
    with pytest.raises(ValueError, match='Invalid sshd'):
        ssh.action('enable', {**SSH_OWNER, 'sources': ['192.168.1.10'], 'ssh_password': SSH_PASSWORD})
    assert not ssh.read()['enabled'] and not active['value']
    assert not ssh.SUDOERS.exists()
    assert not any(args == ['chpasswd'] for args, opts in calls)


def test_failed_pc_update_blocks_component_install_but_not_configuring_existing_ssh(controller):
    ssh.pc.write_state('failed', recovery_required=True)
    assert ssh.action('enable', {**SSH_OWNER, 'sources': ['192.168.1.10'], 'ssh_password': SSH_PASSWORD})['active']
    ssh.SSHD.unlink()
    with pytest.raises(ValueError, match='recover the PC update'):
        ssh.action('install', {})


def test_preview_cannot_modify_ssh(monkeypatch):
    monkeypatch.setattr(ssh, 'installed', lambda: False)
    assert ssh.action('status', {})['supported'] is False
    for action in ('enable', 'disable', 'install'):
        with pytest.raises(ValueError, match='installed AirLink'):
            ssh.action(action, {})


def test_package_failure_sets_recovery_and_does_not_enable_ssh(controller, monkeypatch):
    ssh.SSHD.unlink()
    def package_run(args, **kwargs):
        if '--no-download' in args:
            raise RuntimeError('Package installation failed')
        return ''
    monkeypatch.setattr(ssh.pc, 'run', package_run)
    with pytest.raises(RuntimeError, match='Package installation failed'):
        ssh.install_worker()
    assert ssh.update.read(ssh.pc.ROOT / 'state.json', {})['recovery_required'] is True
    assert ssh.update.read(ssh.ROOT / 'install.json', {})['status'] == 'failed'
    assert not ssh.read()['enabled']


def test_failed_update_is_not_bypassed_by_install_worker(controller, monkeypatch):
    ssh.SSHD.unlink()
    ssh.pc.write_state('failed', recovery_required=True)
    monkeypatch.setattr(ssh.pc, 'run', lambda *a, **k: pytest.fail('Recovery bypassed'))
    with pytest.raises(ValueError, match='recover the PC update'):
        ssh.install_worker()
    assert ssh.update.read(ssh.pc.ROOT / 'state.json', {})['recovery_required'] is True


def test_password_sync_requires_matching_owner_and_prepared_token(controller):
    calls, _, _ = controller
    ssh.action('enable', {**SSH_OWNER, 'sources': ['192.168.1.10'], 'ssh_password': PASSWORD})
    before = len(calls)
    other = ssh.action('password.prepare', {'owner_id': 'another-owner', 'ssh_password': 'New-Owner-Password-937!'})
    assert not other['prepared'] and len(calls) == before
    with pytest.raises(ValueError, match='synchronization changed'):
        ssh.action('password.finish', {**SSH_OWNER, 'token': '', 'ssh_password': PASSWORD})
    prepared = ssh.action('password.prepare', {**SSH_OWNER, 'ssh_password': 'New-Owner-Password-937!'})
    assert prepared['prepared'] and ssh.status()['password_sync_pending']
    assert any(args == ['usermod', '--lock', ssh.USER] for args, opts in calls[before:])
    with pytest.raises(ValueError, match='synchronization changed'):
        ssh.action('password.finish', {**SSH_OWNER, 'token': 'wrong', 'ssh_password': PASSWORD})
    ssh.action('password.finish', {**SSH_OWNER, 'token': prepared['token'], 'ssh_password': 'New-Owner-Password-937!'})
    assert not ssh.status()['password_sync_pending']
    assert [opts['secret'] for args, opts in calls if args == ['chpasswd']][-1] == ssh.USER + ':New-Owner-Password-937!\n'


def test_owner_login_password_change_updates_linked_ssh(client, owner, controller, monkeypatch):
    calls, _, _ = controller
    monkeypatch.setattr(api, 'broker', lambda action, payload=None: ssh.action(action.removeprefix('ssh.'), payload or {}))
    enabled = client.post('/api/system/ssh/enable', headers=owner,
                          json={'owner_password': PASSWORD, 'sources': ['192.168.1.10']})
    assert enabled.status_code == 200, enabled.text
    assert enabled.json()['password_account'] == 'owner'
    new = 'New-Owner-Login-Password-937!'
    changed = client.put('/api/auth/password', headers=owner,
                         json={'current_password': PASSWORD, 'new_password': new, 'confirm_password': new})
    assert changed.status_code == 200 and not changed.json().get('ssh_sync_pending'), changed.text
    assert [opts['secret'] for args, opts in calls if args == ['chpasswd']] == [ssh.USER + ':' + PASSWORD + '\n', ssh.USER + ':' + new + '\n']
    assert client.post('/api/auth/login', json={'username': 'owner', 'password': PASSWORD}).status_code == 401
    assert client.post('/api/auth/login', json={'username': 'owner', 'password': new}).status_code == 200
    assert not ssh.status()['password_sync_pending']
    assert new not in json.dumps(ssh.read())


def test_database_failure_leaves_ssh_locked_for_review(client, owner, controller, monkeypatch):
    calls, _, _ = controller
    monkeypatch.setattr(api, 'broker', lambda action, payload=None: ssh.action(action.removeprefix('ssh.'), payload or {}))
    assert client.post('/api/system/ssh/enable', headers=owner,
                       json={'owner_password': PASSWORD, 'sources': ['192.168.1.10']}).status_code == 200
    original = api.commit
    def fail(db, user, action, target=None):
        if action == 'auth.password_change':
            raise RuntimeError('Database unavailable')
        return original(db, user, action, target)
    monkeypatch.setattr(api, 'commit', fail)
    new = 'New-Owner-Login-Password-937!'
    with pytest.raises(RuntimeError, match='Database unavailable'):
        client.put('/api/auth/password', headers=owner,
                   json={'current_password': PASSWORD, 'new_password': new, 'confirm_password': new})
    assert ssh.status()['password_sync_pending']
    assert [opts['secret'] for args, opts in calls if args == ['chpasswd']] == [ssh.USER + ':' + PASSWORD + '\n']
    assert client.post('/api/auth/login', json={'username': 'owner', 'password': PASSWORD}).status_code == 200


def test_failed_ssh_finish_reports_changed_login_and_recovery(client, owner, controller, monkeypatch):
    monkeypatch.setattr(api, 'broker', lambda action, payload=None: ssh.action(action.removeprefix('ssh.'), payload or {}))
    assert client.post('/api/system/ssh/enable', headers=owner,
                       json={'owner_password': PASSWORD, 'sources': ['192.168.1.10']}).status_code == 200
    original = ssh.run
    def fail(args, **kwargs):
        if args == ['chpasswd']:
            raise ValueError('Password service unavailable')
        return original(args, **kwargs)
    monkeypatch.setattr(ssh, 'run', fail)
    new = 'New-Owner-Login-Password-937!'
    response = client.put('/api/auth/password', headers=owner,
                          json={'current_password': PASSWORD, 'new_password': new, 'confirm_password': new})
    assert response.status_code == 200 and response.json()['ssh_sync_pending']
    assert ssh.status()['password_sync_pending']
    assert client.post('/api/auth/login', json={'username': 'owner', 'password': new}).status_code == 200
    assert client.post('/api/auth/login', json={'username': 'owner', 'password': PASSWORD}).status_code == 401


def test_owner_password_is_unchanged_when_sync_cannot_be_prepared(client, owner, monkeypatch):
    def unavailable(*args, **kwargs):
        raise HTTPException(503, 'Controller unavailable')
    monkeypatch.setattr(api, 'broker', unavailable)
    new = 'New-Owner-Login-Password-937!'
    response = client.put('/api/auth/password', headers=owner,
                          json={'current_password': PASSWORD, 'new_password': new, 'confirm_password': new})
    assert response.status_code == 503
    assert client.post('/api/auth/login', json={'username': 'owner', 'password': PASSWORD}).status_code == 200


def test_owner_password_change_without_enabled_ssh_does_not_create_linux_account(client, owner, controller, monkeypatch):
    calls, accounts, _ = controller
    monkeypatch.setattr(api, 'broker', lambda action, payload=None: ssh.action(action.removeprefix('ssh.'), payload or {}))
    new = 'New-Owner-Login-Password-937!'
    response = client.put('/api/auth/password', headers=owner,
                          json={'current_password': PASSWORD, 'new_password': new, 'confirm_password': new})
    assert response.status_code == 200 and not response.json().get('ssh_sync_pending')
    assert not calls and not accounts
    assert client.post('/api/auth/login', json={'username': 'owner', 'password': new}).status_code == 200
