import hashlib
import json
from datetime import timedelta
import httpx
import pytest
from fastapi import HTTPException
from airlink import deye
from airlink.db import SessionLocal
from airlink.models import DeyeConnection, UserSectionAccess, UserSectionEdits, now
from test_api import user

PATH = '/api/integrations/deye'
CONFIG = {'region': 'eu', 'login_type': 'email', 'account': 'owner@example.invalid',
          'app_id': 'app123', 'app_secret': 'private-app-secret', 'password': 'private-password'}


@pytest.fixture
def cloud(monkeypatch):
    calls = []
    def request(region, path, body, token=None, app_id=None):
        calls.append((region, path, body, token, app_id))
        if path == '/account/token':
            return {'success': True, 'accessToken': body.get('email', body.get('username', body.get('mobile'))) + '-token', 'expiresIn': '3600'}
        if path == '/station/list':
            return {'success': True, 'stationList': [{'id': 123, 'name': 'North solar', 'connectionStatus': 'NORMAL', 'contactPhone': 'private'}], 'total': 1}
        if path == '/station/device':
            return {'success': True, 'deviceListItems': [], 'total': 0}
        return {'success': True, 'generationPower': 4200, 'consumptionPower': 1800,
                'batterySOC': 76, 'batteryPower': -2000, 'chargePower': 2000, 'dischargePower': 0,
                'gridPower': 400, 'purchasePower': 0, 'wirePower': 400, 'lastUpdateTime': now().timestamp()}
    monkeypatch.setattr(deye, 'request', request)
    return calls


def test_connection_encrypts_secrets_and_cloud_contract(client, owner, cloud):
    assert client.get(PATH, headers=owner).json() == {'configured': False}
    response = client.put(PATH, headers=owner, json=CONFIG)
    assert response.status_code == 200, response.text
    for secret in (CONFIG['password'], CONFIG['app_secret'], '-token'):
        assert secret not in response.text
    region, path, payload, _, app_id = cloud[0]
    assert region == 'eu' and path == '/account/token' and app_id == CONFIG['app_id']
    assert payload['password'] == hashlib.sha256(CONFIG['password'].encode()).hexdigest()
    with SessionLocal() as db:
        row = db.query(DeyeConnection).one()
        assert CONFIG['password'] not in row.encrypted_credentials
        assert CONFIG['app_secret'] not in row.encrypted_credentials
        assert deye.decrypt(row.encrypted_credentials)['app_secret'] == CONFIG['app_secret']
        assert '-token' not in row.encrypted_token
    stations = client.get(PATH + '/stations', headers=owner)
    assert stations.status_code == 200 and 'contactPhone' not in stations.text
    assert len(cloud) == 2  # Initial list is cached.
    result = client.get(PATH + '/stations/123/latest', headers=owner).json()
    assert result['solar_w'] == 4200 and result['battery_soc'] == 76 and result['charge_w'] == 2000
    assert result['import_w'] == 0 and result['freshness'] == 'recent'
    assert client.get(PATH + '/stations/123/latest', headers=owner).status_code == 200
    assert len(cloud) == 4  # Includes cached inverter discovery for grid status.
    with SessionLocal() as db:
        row = db.query(DeyeConnection).one()
        cached = dict(row.cache)
        cached['readings'] = {'123': {**cached['readings']['123'], 'at': deye.time.time() - 6}}
        row.cache = cached
        db.commit()
    assert client.get(PATH + '/stations/123/latest', headers=owner).status_code == 200
    assert len(cloud) == 5  # Readings older than five seconds are fetched again.
    kept = {key: value for key, value in CONFIG.items() if key not in ('password', 'app_secret')}
    assert client.put(PATH, headers=owner, json=kept).status_code == 200
    assert client.put(PATH, headers=owner, json={**kept, 'region': 'am'}).status_code == 422


def test_owner_shares_readings_without_credentials_or_delegated_configuration(client, owner, cloud):
    manager_id, manager = user(client, owner, 'manager', 'wakil')
    assert client.get(PATH, headers=manager).status_code == 403
    with SessionLocal() as db:
        db.add(UserSectionAccess(user_id=manager_id, sections=['deye']))
        db.add(UserSectionEdits(user_id=manager_id, sections=['deye']))
        db.commit()
    assert client.get(PATH, headers=manager).status_code == 403
    assert client.put(PATH, headers=manager, json=CONFIG).status_code == 403
    assert client.put(PATH, headers=owner, json=CONFIG).status_code == 200
    assert client.put(PATH + '/sharing/' + manager_id, headers=owner, json={'enabled': True}).status_code == 200
    result = client.get(PATH, headers=manager).json()
    assert result == {'configured': True, 'shared': True, 'dashboard_station': None}
    assert client.get(PATH + '/stations/123/latest', headers=manager).json()['battery_soc'] == 76
    assert client.put(PATH, headers=manager, json=CONFIG).status_code == 403
    assert client.delete(PATH, headers=manager).status_code == 403
    assert client.put(PATH + '/dashboard-station', headers=manager, json={'station_id': None}).status_code == 403
    identity = client.get('/api/auth/me', headers=manager).json()
    assert identity['show_deye_solar'] and 'deye' in identity['sections']
    assert 'deye' not in identity['editable_sections'] and 'deye' not in identity['deletable_sections']
    tokens = [call[3] for call in cloud if call[1] == '/station/latest']
    assert tokens == ['owner@example.invalid-token']
    with SessionLocal() as db:
        assert db.query(DeyeConnection).count() == 1
    assert client.put(PATH + '/sharing/' + manager_id, headers=owner, json={'enabled': False}).status_code == 200
    calls = len(cloud)
    for endpoint in (PATH, PATH + '/stations', PATH + '/stations/123/latest'):
        assert client.get(endpoint, headers=manager).status_code == 403
    assert len(cloud) == calls
    assert not client.get('/api/auth/me', headers=manager).json()['show_deye_solar']


def test_expired_token_renews_and_failed_login_preserves_saved_connection(client, owner, cloud, monkeypatch):
    client.put(PATH, headers=owner, json=CONFIG)
    with SessionLocal() as db:
        row = db.query(DeyeConnection).one()
        row.token_expires = now() - timedelta(seconds=1)
        db.commit()
    client.get(PATH + '/stations/123/latest', headers=owner)
    assert len([call for call in cloud if call[1] == '/account/token']) == 2
    monkeypatch.setattr(deye, 'login', lambda *args: (_ for _ in ()).throw(HTTPException(502, 'Rejected')))
    assert client.put(PATH, headers=owner, json={**CONFIG, 'account': 'wrong@example.invalid'}).status_code == 502
    assert client.get(PATH, headers=owner).json()['account'] == CONFIG['account']


def test_missing_invalid_stale_and_zero_readings():
    old = now() - timedelta(hours=1)
    result = deye.normalized({'lastUpdateTime': old.isoformat(), 'batterySOC': 130,
                             'generationPower': 0, 'consumptionPower': 'NaN', 'gridPower': True})
    assert result['freshness'] == 'stale' and result['solar_w'] == 0
    assert result['battery_soc'] is None and result['load_w'] is None and result['grid_w'] is None
    assert deye.normalized({})['freshness'] == 'unknown'
    assert deye.normalized({'lastUpdateTime': '2026-01-01T00:00:00'})['observed_at'] is None


def test_invalid_connection_input_never_echoes_secrets(client, owner):
    response = client.put(PATH, headers=owner, json={**CONFIG, 'region': 'bad', 'password': ['do-not-echo-me']})
    assert response.status_code == 422
    assert 'do-not-echo-me' not in response.text and CONFIG['app_secret'] not in response.text


def test_https_contract_and_vendor_error_redaction():
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={'success': True, 'stationList': [], 'total': 0})
    deye.request('am', '/station/list', {'page': 1, 'size': 50}, token='secret-token', transport=httpx.MockTransport(handler))
    assert str(requests[0].url) == 'https://us1-developer.deyecloud.com/v1.0/station/list'
    assert requests[0].headers['Authorization'] == 'Bearer secret-token'
    assert json.loads(requests[0].content) == {'page': 1, 'size': 50}
    with pytest.raises(HTTPException) as exc:
        deye.request('eu', '/account/token', {}, transport=httpx.MockTransport(lambda r: httpx.Response(200,
            json={'success': False, 'msg': 'private-password private-app-secret'})))
    assert 'private-' not in str(exc.value.detail)
    with pytest.raises(HTTPException):
        deye.request('eu', '/station/list', {}, transport=httpx.MockTransport(lambda r:
            httpx.Response(302, headers={'Location': 'https://example.invalid/steal'})))


def test_connection_migration_preserves_existing_accounts(tmp_path):
    import importlib.util
    from pathlib import Path
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import create_engine, inspect, text
    path = Path(__file__).resolve().parents[1] / 'database/versions/e05fd472863c_deye_cloud.py'
    spec = importlib.util.spec_from_file_location('deye_migration', path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine('sqlite:///' + str(tmp_path / 'migration.sqlite'))
    with engine.begin() as connection:
        connection.execute(text('CREATE TABLE users (id VARCHAR(36) PRIMARY KEY, username TEXT)'))
        connection.execute(text("INSERT INTO users VALUES ('existing-id', 'existing-owner')"))
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        assert 'deye_connections' in inspect(connection).get_table_names()
        assert connection.execute(text('SELECT username FROM users')).scalar() == 'existing-owner'
        migration.downgrade()
        assert 'deye_connections' not in inspect(connection).get_table_names()
        assert connection.execute(text('SELECT username FROM users')).scalar() == 'existing-owner'
    engine.dispose()


def test_dashboard_station_persists_validates_inventory_and_is_account_scoped(client, owner, cloud, monkeypatch):
    original = deye.request
    def paginated(region, path, body, **kwargs):
        if path == '/station/list' and body['page'] == 2:
            return {'success': True, 'stationList': [{'id': 456, 'name': 'South solar'}], 'total': 51}
        return original(region, path, body, **kwargs)
    monkeypatch.setattr(deye, 'request', paginated)
    assert client.put(PATH, headers=owner, json=CONFIG).status_code == 200
    url = PATH + '/dashboard-station'
    selected = client.put(url, headers=owner, json={'station_id': '456', 'page': 2})
    assert selected.status_code == 200, selected.text
    expected = {'id': '456', 'name': 'South solar', 'page': 2}
    assert selected.json()['dashboard_station'] == expected
    assert client.get(PATH, headers=owner).json()['dashboard_station'] == expected
    assert client.put(url, headers=owner, json={'station_id': '999', 'page': 2}).status_code == 404
    assert client.put(url, headers=owner, json={'station_id': '456', 'name': 'Untrusted'}).status_code == 422
    assert client.get(PATH, headers=owner).json()['dashboard_station'] == expected

    mid, manager = user(client, owner, 'manager', 'solar-dashboard-reader')
    with SessionLocal() as db:
        db.add(UserSectionAccess(user_id=mid, sections=['deye']))
        db.add(UserSectionEdits(user_id=mid, sections=[]))
        db.commit()
    assert client.put(url, headers=manager, json={'station_id': None}).status_code == 403
    assert client.put(PATH + '/sharing/' + mid, headers=owner, json={'enabled': True}).status_code == 200
    assert client.get(PATH, headers=manager).json()['dashboard_station'] == expected
    assert client.get(PATH, headers=owner).json()['dashboard_station'] == expected
    # Updating the same credentials preserves the station; a different cloud account does not.
    assert client.put(PATH, headers=owner, json=CONFIG).json()['dashboard_station'] == expected
    assert client.put(PATH, headers=owner, json={**CONFIG, 'account': 'new@example.invalid'}).json()['dashboard_station'] is None
    assert client.put(url, headers=owner, json={'station_id': '123'}).status_code == 200
    assert client.put(url, headers=owner, json={'station_id': None}).json()['dashboard_station'] is None


def test_dashboard_station_migration_preserves_saved_connection(tmp_path):
    import importlib.util
    from pathlib import Path
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import create_engine, text, inspect
    engine = create_engine('sqlite:///' + str(tmp_path / 'dashboard-migration.sqlite'))
    with engine.begin() as connection:
        connection.execute(text('CREATE TABLE deye_connections (user_id TEXT PRIMARY KEY, encrypted_credentials TEXT)'))
        connection.execute(text("INSERT INTO deye_connections VALUES ('owner', 'saved-encrypted-credentials')"))
        spec = importlib.util.spec_from_file_location('dashboard_migration', Path(__file__).resolve().parents[1] /
                                                     'database/versions/f16ae583974d_deye_dashboard_station.py')
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        assert connection.execute(text('SELECT dashboard_station FROM deye_connections')).scalar() is None
        assert connection.execute(text('SELECT encrypted_credentials FROM deye_connections')).scalar() == 'saved-encrypted-credentials'
        migration.downgrade()
        assert 'dashboard_station' not in {column['name'] for column in inspect(connection).get_columns('deye_connections')}
        assert connection.execute(text('SELECT encrypted_credentials FROM deye_connections')).scalar() == 'saved-encrypted-credentials'
    engine.dispose()


@pytest.mark.parametrize('custom_role', [False, True], ids=['manager-role', 'custom-role'])
def test_access_roles_cannot_override_owner_sharing_or_grant_configuration(client, owner, cloud, custom_role):
    uid, manager = user(client, owner, 'manager', 'deye-role-manager')
    policy = {'name': 'Wakil', 'sections': ['deye'], 'editable_sections': ['deye'], 'deletable_sections': ['deye']}
    if custom_role:
        created = client.post('/api/access-roles', headers=owner, json=policy)
        assert created.status_code == 201, created.text
        role_id = created.json()['id']
        assigned = client.put('/api/users/' + uid, headers=owner,
                              json={'username': 'deye-role-manager', 'access_role_id': role_id})
        assert assigned.status_code == 200, assigned.text
    else:
        role_id = 'builtin:manager'
        assert client.put('/api/access-roles/' + role_id, headers=owner, json=policy).status_code == 200
    assert client.get(PATH, headers=manager).status_code == 403
    assert client.put(PATH, headers=manager, json=CONFIG).status_code == 403
    assert client.delete(PATH, headers=manager).status_code == 403
    assert cloud == []
    assert client.put(PATH, headers=owner, json=CONFIG).status_code == 200
    assert client.put(PATH + '/sharing/' + uid, headers=owner, json={'enabled': True}).status_code == 200
    assert client.get(PATH + '/stations/123/latest', headers=manager).status_code == 200
    assert client.put(PATH, headers=manager, json=CONFIG).status_code == 403
    assert client.delete(PATH, headers=manager).status_code == 403
    assert client.get(PATH + '/sharing', headers=manager).status_code == 403
    assert client.put(PATH + '/sharing/' + uid, headers=manager, json={'enabled': True}).status_code == 403
    # Explicit sharing also works when a Wakil's role has no Deye section grant.
    policy.update(sections=[], editable_sections=[], deletable_sections=[])
    assert client.put('/api/access-roles/' + role_id, headers=owner, json=policy).status_code == 200
    assert client.get(PATH + '/stations/123/latest', headers=manager).status_code == 200
    assert client.put(PATH + '/sharing/' + uid, headers=owner, json={'enabled': False}).status_code == 200
    assert client.get(PATH, headers=manager).status_code == 403
