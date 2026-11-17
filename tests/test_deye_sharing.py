import importlib.util
import json
from pathlib import Path
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text
from airlink import deye_monitor, live_updates
from airlink.db import SessionLocal
from airlink.models import DeyeConnection, DeyeShare, User, AuditLog
from test_api import user
from test_deye import CONFIG, PATH, cloud


def snapshot(headers):
    return live_updates.snapshot(headers['Authorization'].removeprefix('Bearer '))


def test_share_has_no_configuration_metadata_and_revokes_live_readings(client, owner, cloud):
    uid, wakil = user(client, owner, 'manager', 'wakil-shared')
    client.put(PATH, headers=owner, json=CONFIG)
    owner_id = client.get('/api/auth/me', headers=owner).json()['id']
    assert client.put(PATH+'/sharing/'+uid, headers=owner, json={'enabled': True}).status_code == 200
    deye_monitor.poll_account(owner_id)
    before = snapshot(wakil)
    assert before['user']['show_deye_solar']
    assert before['deye']['readings']['123']['solar_w'] == 4200
    payload = json.dumps(before['deye']) + client.get(PATH, headers=wakil).text
    for value in (CONFIG['account'], CONFIG['app_id'], CONFIG['app_secret'], CONFIG['password'], '-token', 'region'):
        assert value not in payload
    calls = len(cloud)
    client.get(PATH+'/stations/123/latest', headers=wakil)
    assert len(cloud) == calls  # Uses the owner's existing cache and grid history.
    assert client.put(PATH+'/sharing/'+uid, headers=owner, json={'enabled': False}).status_code == 200
    after = snapshot(wakil)
    patch = live_updates.changes(before, after)
    assert patch['deye'] is None and not patch['user']['show_deye_solar']
    assert 'deye' not in patch['user']['sections']
    with SessionLocal() as db:
        assert db.get(DeyeShare, uid) is None
        assert db.query(AuditLog).filter(AuditLog.action == 'deye.share').count() == 1
        assert db.query(AuditLog).filter(AuditLog.action == 'deye.unshare').count() == 1


def test_each_owner_shares_only_their_connection_and_legacy_nonowners_are_dormant(client, owner, cloud):
    other_id, other = user(client, owner, 'owner', 'second-owner')
    viewer_id, viewer = user(client, owner, 'viewer', 'solar-viewer')
    client.put(PATH, headers=owner, json=CONFIG)
    other_config = {**CONFIG, 'account': 'second@example.invalid'}
    client.put(PATH, headers=other, json=other_config)
    assert client.put(PATH+'/sharing/'+viewer_id, headers=other, json={'enabled': True}).status_code == 200
    assert client.put(PATH+'/sharing/'+viewer_id, headers=owner, json={'enabled': True}).status_code == 409
    assert client.put(PATH+'/sharing/'+viewer_id, headers=owner, json={'enabled': False}).status_code == 409
    assert client.get(PATH+'/stations/123/latest', headers=viewer).status_code == 200
    assert [call[3] for call in cloud if call[1] == '/station/latest'] == ['second@example.invalid-token']
    with SessionLocal() as db:
        # Simulate a pre-upgrade non-owner connection. It is preserved but never used.
        db.get(User, other_id).role = 'manager'
        original_credentials = db.get(DeyeConnection, other_id).encrypted_credentials
        db.commit()
    assert client.get(PATH, headers=viewer).status_code == 403  # Sharing owner no longer has owner authority.
    calls = len(cloud)
    deye_monitor.poll_account(other_id)
    assert len(cloud) == calls
    assert client.put(PATH+'/sharing/'+other_id, headers=owner, json={'enabled': True}).status_code == 200
    assert client.get(PATH+'/stations/123/latest', headers=other).status_code == 200
    assert [call[3] for call in cloud if call[1] == '/station/latest'][-1] == 'owner@example.invalid-token'
    with SessionLocal() as db:
        assert db.get(DeyeConnection, other_id).encrypted_credentials == original_credentials


def test_sharing_validation_and_owner_only_list(client, owner):
    uid, wakil = user(client, owner, 'manager', 'wakil')
    owner_id = client.get('/api/auth/me', headers=owner).json()['id']
    listing = client.get(PATH+'/sharing', headers=owner)
    assert listing.status_code == 200 and listing.json()[0]['username'] == 'wakil'
    assert not listing.json()[0]['enabled']
    assert client.get(PATH+'/sharing', headers=wakil).status_code == 403
    assert client.put(PATH+'/sharing/'+uid, headers=wakil, json={'enabled': True}).status_code == 403
    assert client.put(PATH+'/sharing/'+uid, headers=owner, json={'enabled': 'yes'}).status_code == 422
    assert client.put(PATH+'/sharing/'+owner_id, headers=owner, json={'enabled': True}).status_code == 422
    assert client.put(PATH+'/sharing/missing', headers=owner, json={'enabled': True}).status_code == 404
    with SessionLocal() as db:
        db.get(User, uid).active = False
        db.commit()
    assert client.put(PATH+'/sharing/'+uid, headers=owner, json={'enabled': True}).status_code == 422
    client.cookies.clear()
    assert client.get(PATH+'/sharing').status_code == 401


def test_migration_preserves_connections_and_defaults_to_no_sharing(tmp_path):
    path = Path(__file__).resolve().parents[1]/'database/versions/c05de1286431_deye_owner_sharing.py'
    spec = importlib.util.spec_from_file_location('sharing_migration', path)
    migration = importlib.util.module_from_spec(spec); spec.loader.exec_module(migration)
    engine = create_engine('sqlite:///'+str(tmp_path/'migration.sqlite'))
    with engine.begin() as connection:
        connection.execute(text('CREATE TABLE users (id VARCHAR(36) PRIMARY KEY)'))
        connection.execute(text("INSERT INTO users VALUES ('owner'), ('wakil')"))
        connection.execute(text('CREATE TABLE deye_connections (user_id TEXT PRIMARY KEY, encrypted_credentials TEXT)'))
        connection.execute(text("INSERT INTO deye_connections VALUES ('owner', 'preserved')"))
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        assert 'deye_shares' in inspect(connection).get_table_names()
        assert connection.execute(text('SELECT count(*) FROM deye_shares')).scalar() == 0
        assert connection.execute(text('SELECT encrypted_credentials FROM deye_connections')).scalar() == 'preserved'
        migration.downgrade()
        assert 'deye_shares' not in inspect(connection).get_table_names()
        assert connection.execute(text('SELECT encrypted_credentials FROM deye_connections')).scalar() == 'preserved'
    engine.dispose()
