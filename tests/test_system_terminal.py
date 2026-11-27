import json
from types import SimpleNamespace
import pytest
from sqlalchemy import select
from airlink import api
from airlink.db import SessionLocal
from airlink.models import AuditLog, User
from airlink.security import hasher
from console import web_terminal as terminal
from conftest import PASSWORD


def test_terminal_requires_owner_password_and_does_not_forward_it(client, owner, monkeypatch):
    calls = []
    monkeypatch.setattr(api, 'broker', lambda action, payload: calls.append((action, payload)) or {'session_id': 'a' * 48})
    assert client.post('/api/system/terminal/open', json={'password': PASSWORD}).status_code == 401
    bad = client.post('/api/system/terminal/open', headers=owner, json={'password': 'wrong'})
    assert bad.status_code == 403
    assert not calls
    response = client.post('/api/system/terminal/open', headers=owner, json={'password': PASSWORD})
    assert response.status_code == 201
    assert calls[0][0] == 'terminal.open'
    assert calls[0][1]['owner_id'] and calls[0][1]['login_session']
    assert 'password' not in calls[0][1]
    with SessionLocal() as db:
        actions = [row.action for row in db.scalars(select(AuditLog))]
    assert 'terminal.open' in actions
    assert 'terminal.authentication_failed' in actions


@pytest.mark.parametrize('role', ['manager', 'technician', 'viewer'])
def test_other_roles_cannot_use_any_terminal_endpoint(client, owner, role, monkeypatch):
    with SessionLocal() as db:
        db.add(User(username='other', role=role, password_hash=hasher.hash(PASSWORD)))
        db.commit()
    token = client.post('/api/auth/login', json={'username': 'other', 'password': PASSWORD}).json()['access_token']
    headers = {'Authorization': 'Bearer ' + token}
    monkeypatch.setattr(api, 'broker', lambda *a: pytest.fail('Non-owner reached root controller'))
    assert client.get('/api/system/terminal', headers=headers).status_code == 403
    for action, payload in [('open', {'password': PASSWORD}),
                            ('exchange', {'session_id': 'a'*48, 'sequence': 0, 'cursor': 0}),
                            ('close', {'session_id': 'a'*48})]:
        assert client.post('/api/system/terminal/' + action, json=payload, headers=headers).status_code == 403


def test_terminal_password_rate_limit_and_validation_redaction(client, owner, monkeypatch):
    monkeypatch.setattr(api, 'broker', lambda *a: pytest.fail('Invalid input reached root controller'))
    response = client.post('/api/system/terminal/open', headers=owner,
                           json={'password': PASSWORD, 'cols': 'invalid', 'secret': 'PrivateValue'})
    assert response.status_code == 422
    assert PASSWORD not in response.text and 'PrivateValue' not in response.text
    for _ in range(5):
        assert client.post('/api/system/terminal/open', headers=owner, json={'password': 'bad'}).status_code == 403
    assert client.post('/api/system/terminal/open', headers=owner, json={'password': PASSWORD}).status_code == 429


def test_revoked_login_cannot_continue_terminal(client, owner, monkeypatch):
    monkeypatch.setattr(api, 'broker', lambda *a: pytest.fail('Revoked login reached controller'))
    assert client.post('/api/auth/logout', headers=owner).status_code == 200
    response = client.post('/api/system/terminal/exchange', headers=owner,
                           json={'session_id': 'a'*48, 'sequence': 0, 'cursor': 0})
    assert response.status_code == 401


@pytest.fixture
def session_service(monkeypatch, tmp_path):
    commands = []
    monkeypatch.setattr(terminal, 'supported', lambda: True)
    monkeypatch.setattr(terminal.os, 'geteuid', lambda: 0)
    monkeypatch.setattr(terminal.update, 'ROOT', tmp_path / 'updates')
    monkeypatch.setattr(terminal.update, 'restart_status', lambda: {'pending': False})
    monkeypatch.setattr(terminal.pc, 'ROOT', tmp_path / 'pc-updates')
    monkeypatch.setattr(terminal.subprocess, 'run', lambda args, **kw: commands.append(args) or SimpleNamespace(returncode=0))
    monkeypatch.setattr(terminal.threading, 'Thread', lambda **kw: SimpleNamespace(start=lambda: None))
    service = terminal.TerminalService()
    identity = {'owner_id': 'owner', 'login_session': 'login-1'}
    opened = service.action('open', {**identity, 'cols': 100, 'rows': 30})
    payload = {**identity, **opened, 'sequence': 0, 'cursor': 0, 'data': '', 'cols': 100, 'rows': 30}
    yield service, payload, commands
    service.session.close()


def test_shell_has_root_environment_lifetime_and_process_tree_cleanup(session_service):
    service, payload, commands = session_service
    assert '--property=RuntimeMaxSec=900' in commands[0]
    assert '--property=KillMode=control-group' in commands[0]
    assert '--property=BindsTo=airlink-controller.service' in commands[0]
    assert 'HISTFILE=/dev/null' in commands[0]
    assert '/usr/bin/flock' in commands[0] and '--no-fork' in commands[0]
    assert '--norc' in commands[0]
    service.action('close', payload)
    assert service.session.closed
    assert commands[-1] == ['systemctl', 'stop', '--no-block', service.session.unit]


def test_session_cannot_be_used_by_another_owner_or_login(session_service):
    service, payload, _ = session_service
    for field in ['owner_id', 'login_session', 'session_id']:
        with pytest.raises(ValueError, match='another login'):
            service.action('exchange', {**payload, field: 'other'})
        with pytest.raises(ValueError, match='another login'):
            service.action('close', {**payload, field: 'other'})
    with pytest.raises(ValueError, match='already open'):
        service.action('open', payload)


def test_input_is_not_repeated_when_exchange_is_replayed(session_service, monkeypatch):
    service, payload, _ = session_service
    writes = []
    monkeypatch.setattr(terminal.os, 'write', lambda fd, data: writes.append(data) or len(data))
    command = {**payload, 'sequence': 1, 'data': 'printf hello\r'}
    service.action('exchange', command)
    service.action('exchange', command)
    assert writes == [b'printf hello\r']
    with pytest.raises(ValueError, match='sequence'):
        service.action('exchange', {**command, 'sequence': 3})


def test_output_has_bounded_replayable_chunks_and_reports_truncation(session_service):
    service, payload, _ = session_service
    service.session.output = '\U0001f600' * 40000
    service.session.offset = 100
    first = service.action('exchange', payload)
    assert first['truncated'] is True and first['cursor'] == 16484
    assert len(first['output']) == 16384
    assert len(json.dumps(first).encode()) < 1024*1024
    assert service.action('exchange', payload) == first
    second = service.action('exchange', {**payload, 'cursor': first['cursor']})
    assert not second['truncated'] and second['cursor'] == 32868
    service.session.close()
    assert service.action('exchange', payload)['closed'] is False
    final = service.action('exchange', {**payload, 'cursor': second['cursor']})
    assert final['closed'] is True and final['cursor'] == 40100


@pytest.mark.parametrize('cause,reason', [('age', 'Session expired'), ('idle', 'Browser disconnected')])
def test_abandoned_or_expired_session_is_stopped(session_service, cause, reason):
    service, _, commands = session_service
    if cause == 'age':
        service.session.created -= terminal.LIFETIME + 1
    else:
        service.session.touched -= terminal.DISCONNECT_GRACE + 1
    service.session._watch()
    assert service.session.closed and service.session.reason == reason
    assert commands[-1][0:2] == ['systemctl', 'stop']


def test_preview_never_starts_a_shell(monkeypatch):
    monkeypatch.setattr(terminal, 'supported', lambda: False)
    service = terminal.TerminalService()
    assert service.action('status', {})['supported'] is False
    with pytest.raises(ValueError, match='installed AirLink Linux PC'):
        service.action('open', {})


def test_terminal_serializes_maintenance_but_allows_failed_update_review(tmp_path, monkeypatch):
    monkeypatch.setattr(terminal.update, 'ROOT', tmp_path / 'updates')
    monkeypatch.setattr(terminal.pc, 'ROOT', tmp_path / 'pc-updates')
    monkeypatch.setattr(terminal.update, 'restart_status', lambda: {'pending': False})
    with terminal.pc.maintenance_lock():
        with pytest.raises(ValueError, match='active'):
            terminal.maintenance_ready()
    terminal.update.atomic(terminal.update.ROOT / 'state.json', {'status': 'queued'})
    with pytest.raises(ValueError, match='pending'):
        terminal.maintenance_ready()
    terminal.update.atomic(terminal.update.ROOT / 'state.json', {'status': 'failed', 'recovery_required': True})
    terminal.maintenance_ready()
    terminal.pc.write_state('queued_install')
    with pytest.raises(ValueError, match='pending'):
        terminal.maintenance_ready()
    terminal.pc.write_state('failed', recovery_required=True)
    terminal.maintenance_ready()
