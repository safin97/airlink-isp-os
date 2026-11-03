import json
from airlink import online_device, sas4, sas4_reports
from airlink.db import SessionLocal
from airlink.models import DeviceLoginProfile
from airlink.security import cipher
from test_api import user

PATH = '/api/integrations/sas4/device-login-profiles'
BODY = {'name': 'Roof devices', 'username': 'reader', 'password': 'private-device-password', 'protocol': 'both'}


def create(client, owner):
    result = client.post(PATH, headers=owner, json=BODY)
    assert result.status_code == 201, result.text
    assert BODY['password'] not in result.text and 'encrypted_config' not in result.text
    return result.json()['id']


def test_profiles_are_encrypted_account_scoped_and_passwords_preserved(client, owner):
    pid = create(client, owner)
    with SessionLocal() as db:
        row = db.get(DeviceLoginProfile, pid)
        assert BODY['password'] not in row.encrypted_config
        assert json.loads(cipher().decrypt(row.encrypted_config.encode()))['api_password'] == BODY['password']
    assert BODY['password'] not in client.get(PATH, headers=owner).text
    updated = client.put(PATH + '/' + pid, headers=owner, json={**BODY, 'name': 'Renamed', 'password': None})
    assert updated.status_code == 200 and updated.json()['has_password'] is True
    assert client.put(PATH + '/' + pid, headers=owner, json={**BODY, 'username': 'other', 'password': None}).status_code == 422
    _, manager = user(client, owner, 'manager')
    assert client.get(PATH, headers=manager).json() == []
    assert client.put(PATH + '/' + pid, headers=manager, json=BODY).status_code == 404
    assert client.delete(PATH + '/' + pid, headers=manager).status_code == 404
    assert client.post(PATH, headers=manager, json=BODY).status_code == 201
    assert client.delete(PATH + '/' + pid, headers=owner).status_code == 204
    assert client.get(PATH, headers=owner).json() == []


def test_profile_permissions_and_validation(client, owner):
    mid, manager = user(client, owner, 'manager')
    assert client.put('/api/users/' + mid + '/sections', headers=owner, json={
        'sections': ['isp_card'], 'editable_sections': [], 'deletable_sections': []}).status_code == 200
    assert client.get(PATH, headers=manager).status_code == 200
    assert client.post(PATH, headers=manager, json=BODY).status_code == 403
    assert client.delete(PATH + '/missing', headers=manager).status_code == 403
    assert client.put('/api/users/' + mid + '/sections', headers=owner, json={'sections': []}).status_code == 200
    assert client.get(PATH, headers=manager).status_code == 403
    for change in ({'name': ' '}, {'password': None}, {'port': 0}, {'protocol': 'ftp'}):
        assert client.post(PATH, headers=owner, json={**BODY, **change}).status_code == 422
    create(client, owner)
    assert client.post(PATH, headers=owner, json=BODY).status_code == 409


def test_selected_profile_requires_verified_session_and_own_account(client, owner, monkeypatch):
    pid = create(client, owner)
    assert client.put('/api/integrations/sas4', headers=owner,
        json={'username': 'sas-owner', 'password': 'sas-secret'}).status_code == 200
    monkeypatch.setattr(sas4, 'fetch_clients', lambda *a, **kw: {'clients': [
        {'username': 'subscriber', 'ip_address': '10.2.3.4', 'session_id': 90, 'manager': 'North'}], 'last_page': 1})
    def no_manager_lookup(*a, **kw):
        raise AssertionError('Selected profile must not need the manager default')
    monkeypatch.setattr(sas4_reports, 'fetch_managers', no_manager_lookup)
    calls = []
    async def collect(address, config):
        assert config['api_username'] == 'reader' and config['api_password'] == BODY['password']
        calls.append(address)
        return {'vendor': 'MikroTik', 'wireless': [], 'ethernet': [], 'pppoe': []}
    monkeypatch.setattr(online_device, 'collect', collect)
    query = {'username': 'subscriber', 'ip_address': '10.2.3.4', 'session_id': '90', 'profile_id': pid}
    result = client.get('/api/integrations/sas4/online-device', headers=owner, params=query)
    assert result.status_code == 200, result.text
    assert result.json()['credential_source'] == 'Roof devices'
    assert BODY['password'] not in result.text
    assert client.get('/api/integrations/sas4/online-device', headers=owner, params={**query, 'session_id': '91'}).status_code == 409
    _, manager = user(client, owner, 'manager')
    client.put('/api/integrations/sas4', headers=manager, json={'username': 'sas-manager', 'password': 'sas-secret'})
    assert client.get('/api/integrations/sas4/online-device', headers=manager, params=query).status_code == 404
    client.put(PATH + '/' + pid, headers=owner, json={**BODY, 'enabled': False})
    assert client.get('/api/integrations/sas4/online-device', headers=owner, params=query).status_code == 409
    assert calls == ['10.2.3.4']


def test_profile_migration_preserves_existing_accounts(client, owner):
    import importlib.util
    from pathlib import Path
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import inspect, text
    from airlink.db import engine
    spec = importlib.util.spec_from_file_location('profile_migration',
        Path(__file__).resolve().parents[1] / 'database/versions/27a9f1d4c860_device_login_profiles.py')
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with engine.begin() as connection:
        DeviceLoginProfile.__table__.drop(connection)
        before = connection.execute(text('select id, username from users')).all()
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        assert 'device_login_profiles' in inspect(connection).get_table_names()
        assert connection.execute(text('select id, username from users')).all() == before
        migration.downgrade()
        migration.upgrade()
