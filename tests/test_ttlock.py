import hashlib
import json
from datetime import timedelta
from urllib.parse import parse_qs
import httpx
import pytest
from fastapi import HTTPException
from airlink import ttlock
from airlink.db import SessionLocal
from airlink.models import TTLockConnection, TTLockCommand, TTLockApplication, now
from test_api import user

PATH = '/api/integrations/ttlock'
CONFIG = {'region': 'eu', 'username': '+9647500000000', 'client_id': 'app123',
          'client_secret': 'private-client-secret', 'password': 'private-account-password'}


@pytest.fixture
def cloud(monkeypatch):
    calls = []
    def request(region, path, body):
        calls.append((region, path, dict(body)))
        if path == '/oauth2/token':
            return {'access_token': 'private-access-token', 'refresh_token': 'private-refresh-token', 'expires_in': 3600}
        if path == '/v3/lock/list':
            return {'list': [{'lockId': 42, 'lockAlias': 'Office door', 'electricQuantity': 0, 'hasGateway': 1,
                             'lockData': 'private-lock-data', 'keyboardPwd': 'private-passcode'}], 'pages': 1, 'total': 1}
        if path == '/v3/lock/queryOpenState':
            return {'state': 0}
        return {'errcode': 0}
    monkeypatch.setattr(ttlock, 'request', request)
    return calls


def test_connect_encrypts_tokens_and_never_stores_password(client, owner, cloud):
    result = client.put(PATH, headers=owner, json=CONFIG)
    assert result.status_code == 200, result.text
    assert result.json()['locks']['items'][0]['battery'] == 0
    assert result.headers['cache-control'] == 'no-store'
    for secret in ('private-client-secret', 'private-account-password', 'private-access-token', 'private-lock-data', 'private-passcode'):
        assert secret not in result.text
    assert cloud[0][2]['password'] == hashlib.md5(CONFIG['password'].encode()).hexdigest()
    with SessionLocal() as db:
        row = db.query(TTLockConnection).one()
        assert 'private-' not in row.encrypted_credentials + row.encrypted_token
        saved = ttlock.decrypt(row.encrypted_credentials)
        assert saved['client_secret'] == CONFIG['client_secret']
        assert 'password' not in saved
    assert client.get(PATH, headers=owner).json()['username'] == CONFIG['username']
    assert client.get(PATH + '/locks', headers=owner).json()['items'][0]['id'] == 42
    assert client.delete(PATH, headers=owner).status_code == 200
    assert client.get(PATH, headers=owner).json() == {'configured': False}


def test_rejected_login_preserves_existing_connection(client, owner, cloud, monkeypatch):
    client.put(PATH, headers=owner, json=CONFIG)
    monkeypatch.setattr(ttlock, 'request', lambda *a: (_ for _ in ()).throw(HTTPException(502, 'Rejected')))
    assert client.put(PATH, headers=owner, json={**CONFIG, 'username': 'wrong'}).status_code == 502
    assert client.get(PATH, headers=owner).json()['username'] == CONFIG['username']


def test_owner_only_and_isolated_connections(client, owner, cloud):
    client.put(PATH, headers=owner, json=CONFIG)
    _, other_owner = user(client, owner, 'owner', 'another-owner')
    assert client.get(PATH, headers=other_owner).json() == {'configured': False}
    assert client.get(PATH + '/locks', headers=other_owner).status_code == 409
    for role in ('manager', 'technician', 'viewer'):
        _, headers = user(client, owner, role, 'lock-' + role)
        count = len(cloud)
        for method, suffix, body in [('get', '', None), ('put', '', CONFIG), ('delete', '', None),
                                     ('get', '/locks', None), ('get', '/locks/42/state', None),
                                     ('put', '/locks/42/name', {'name': 'New name'}),
                                     ('post', '/locks/42/action', {'action': 'unlock', 'request_id': 'a' * 32})]:
            kwargs = {'json': body} if body is not None else {}
            assert getattr(client, method)(PATH + suffix, headers=headers, **kwargs).status_code == 403
        assert len(cloud) == count
    assert client.get(PATH).status_code == 401


def test_expiry_refreshes_without_password_and_read_auth_error_retries_once(client, owner, cloud, monkeypatch):
    client.put(PATH, headers=owner, json=CONFIG)
    with SessionLocal() as db:
        row = db.query(TTLockConnection).one()
        row.token_expires = now() - timedelta(seconds=1)
        db.commit()
    assert client.get(PATH + '/locks', headers=owner).status_code == 200
    refreshes = [body for _, path, body in cloud if path == '/oauth2/token' and 'grant_type' in body]
    assert len(refreshes) == 1 and refreshes[0]['grant_type'] == 'refresh_token'
    assert 'password' not in refreshes[0]
    real = ttlock.request
    attempts = []
    def stale(region, path, body):
        if path == '/v3/lock/list':
            attempts.append(path)
            if len(attempts) == 1:
                raise ttlock.ExpiredToken()
        return real(region, path, body)
    monkeypatch.setattr(ttlock, 'request', stale)
    assert client.get(PATH + '/locks', headers=owner).status_code == 200
    assert len(attempts) == 2


def test_lock_commands_require_ownership_and_deduplicate(client, owner, cloud):
    client.put(PATH, headers=owner, json=CONFIG)
    command = {'action': 'unlock', 'request_id': 'a' * 32}
    assert client.post(PATH + '/locks/99/action', headers=owner, json=command).status_code == 404
    assert not [p for _, p, _ in cloud if p == '/v3/lock/unlock']
    for _ in range(2):
        result = client.post(PATH + '/locks/42/action', headers=owner, json=command)
        assert result.status_code == 200 and result.json()['status'] == 'completed'
    assert len([p for _, p, _ in cloud if p == '/v3/lock/unlock']) == 1
    assert client.post(PATH + '/locks/42/action', headers=owner, json={**command, 'action': 'lock'}).status_code == 409
    assert client.post(PATH + '/locks/42/action', headers=owner, json={'action': 'lock', 'request_id': 'b' * 32}).status_code == 200
    assert client.get(PATH + '/locks/42/state', headers=owner).json()['state'] == 'locked'
    assert client.get(PATH + '/locks/99/state', headers=owner).status_code == 404


def test_ambiguous_command_is_not_replayed(client, owner, cloud, monkeypatch):
    client.put(PATH, headers=owner, json=CONFIG)
    real = ttlock.request
    attempts = []
    def timeout(region, path, body):
        if path == '/v3/lock/unlock':
            attempts.append(path)
            raise HTTPException(502, 'Timeout')
        return real(region, path, body)
    monkeypatch.setattr(ttlock, 'request', timeout)
    body = {'action': 'unlock', 'request_id': 'c' * 32}
    result = client.post(PATH + '/locks/42/action', headers=owner, json=body)
    assert result.status_code == 502 and 'Check the physical lock' in result.text
    assert client.post(PATH + '/locks/42/action', headers=owner, json=body).status_code == 409
    assert len(attempts) == 1
    with SessionLocal() as db:
        assert db.query(TTLockCommand).one().status == 'unconfirmed'


def test_invalid_inputs_do_not_echo_secrets(client, owner, cloud):
    result = client.put(PATH, headers=owner, json={**CONFIG, 'password': ['private-leak'], 'region': 'http://localhost'})
    assert result.status_code == 422
    assert 'private-' not in result.text
    assert cloud == []


def test_rename_checks_account_ownership_and_input(client, owner, cloud):
    client.put(PATH, headers=owner, json=CONFIG)
    _, another = user(client, owner, 'owner', 'other-lock-owner')
    assert client.put(PATH + '/locks/42/name', headers=another, json={'name': 'Other'}).status_code == 409
    assert client.put(PATH + '/locks/99/name', headers=owner, json={'name': 'Other'}).status_code == 404
    for name in ('', '   ', 'x' * 101):
        assert client.put(PATH + '/locks/42/name', headers=owner, json={'name': name}).status_code == 422
    assert not [p for _, p, _ in cloud if p.endswith('/rename')]
    result = client.put(PATH + '/locks/42/name', headers=owner, json={'name': '  Main entrance  ', 'page': 1})
    assert result.status_code == 200
    assert result.json() == {'id': 42, 'name': 'Main entrance'}
    payload = [b for _, p, b in cloud if p.endswith('/rename')][0]
    assert payload['lockId'] == 42 and payload['lockAlias'] == 'Main entrance'
    assert result.headers['cache-control'] == 'no-store'


@pytest.mark.parametrize('failure', ['timeout', 'expired', 'malformed'])
def test_rename_requires_confirmation_and_never_retries(client, owner, cloud, monkeypatch, failure):
    client.put(PATH, headers=owner, json=CONFIG)
    real = ttlock.request
    attempts = []
    def failing(region, path, body):
        if path.endswith('/rename'):
            attempts.append(path)
            if failure == 'timeout':
                raise HTTPException(502, 'Timeout')
            if failure == 'expired':
                raise ttlock.ExpiredToken()
            return {}
        return real(region, path, body)
    monkeypatch.setattr(ttlock, 'request', failing)
    result = client.put(PATH + '/locks/42/name', headers=owner, json={'name': 'Main entrance'})
    assert result.status_code == 502
    assert 'Sync devices' in result.json()['detail']
    assert len(attempts) == 1


def test_http_transport_posts_and_filters_provider_errors():
    calls = []
    def remote(request):
        calls.append(request)
        assert request.method == 'POST' and request.url.query == b''
        assert parse_qs(request.content.decode())['clientSecret'] == ['private-secret']
        return httpx.Response(200, json={'errcode': 10007, 'errmsg': 'private-provider-echo'})
    with pytest.raises(HTTPException) as caught:
        ttlock.request('eu', '/oauth2/token', {'clientSecret': 'private-secret'}, transport=httpx.MockTransport(remote))
    assert 'private-' not in caught.value.detail
    assert len(calls) == 1
    with pytest.raises(ValueError):
        ttlock.request('eu', '/v3/key/delete', {})


def test_unknown_state_and_empty_lock_list_are_not_faked(client, owner, cloud, monkeypatch):
    client.put(PATH, headers=owner, json=CONFIG)
    real = ttlock.request
    monkeypatch.setattr(ttlock, 'request', lambda r, p, b: {'state': True} if p.endswith('queryOpenState') else real(r, p, b))
    assert client.get(PATH + '/locks/42/state', headers=owner).json()['state'] == 'unknown'
    monkeypatch.setattr(ttlock, 'request', lambda *a: {'list': [], 'pages': 0, 'total': 0})
    assert client.get(PATH + '/locks', headers=owner).json()['items'] == []


@pytest.mark.parametrize('migration_file, models', [
    ('c19ef8250a36_ttlock.py', (TTLockConnection, TTLockCommand)),
    ('d20fa9361b47_ttlock_application.py', (TTLockApplication,)),
])
def test_migration_preserves_accounts_and_matches_models(client, owner, migration_file, models):
    import importlib.util
    from pathlib import Path
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import inspect, select
    from airlink.db import engine
    from airlink.models import User
    spec = importlib.util.spec_from_file_location('ttlock_migration', Path(__file__).resolve().parents[1] / 'database/versions' / migration_file)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with engine.begin() as connection:
        user_id = connection.execute(select(User.id)).scalar()
        migration.op = Operations(MigrationContext.configure(connection))
        migration.downgrade()
        assert connection.execute(select(User.id)).scalar() == user_id
        migration.upgrade()
        for model in models:
            assert {c['name'] for c in inspect(connection).get_columns(model.__tablename__)} == {c.name for c in model.__table__.columns}


def test_state_transport_matches_documented_get_method():
    def remote(request):
        assert request.method == 'GET'
        assert request.url.params['lockId'] == '42'
        return httpx.Response(200, json={'state': 2})
    assert ttlock.request('eu', '/v3/lock/queryOpenState', {'lockId': 42}, transport=httpx.MockTransport(remote)) == {'state': 2}


def test_username_password_login_uses_saved_application_and_survives_disconnect(client, owner, cloud):
    setup = {k: CONFIG[k] for k in ('region', 'client_id', 'client_secret')}
    assert client.get(PATH + '/application', headers=owner).json() == {'configured': False}
    login = {k: CONFIG[k] for k in ('username', 'password')}
    result = client.put(PATH, headers=owner, json=login)
    assert result.status_code == 409 and 'one-time' in result.text
    assert not cloud
    result = client.put(PATH + '/application', headers=owner, json=setup)
    assert result.status_code == 200 and 'private-' not in result.text
    from airlink.models import TTLockApplication
    with SessionLocal() as db:
        saved = db.query(TTLockApplication).one()
        assert 'private-' not in saved.encrypted_credentials
    for _ in range(2):
        assert client.put(PATH, headers=owner, json=login).status_code == 200
        assert client.delete(PATH, headers=owner).status_code == 200
    assert client.get(PATH + '/application', headers=owner).json()['configured']
    _, other = user(client, owner, 'owner', 'different-lock-owner')
    assert client.get(PATH + '/application', headers=other).json() == {'configured': False}
    _, manager = user(client, owner, 'manager', 'lock-setup-manager')
    assert client.put(PATH + '/application', headers=manager, json=setup).status_code == 403
    assert client.get(PATH + '/application', headers=manager).status_code == 403
