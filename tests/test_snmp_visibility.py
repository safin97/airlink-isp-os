from airlink import live_updates
from airlink.db import SessionLocal
from airlink.models import UserSNMPVisibility
from test_api import user
from conftest import PASSWORD

POLICY = '/api/snmp-profile-visibility'
PROFILES = '/api/snmp-profiles'


def toggle(client, owner, mid, enabled):
    result = client.put('/api/users/' + mid, headers=owner,
        json={'username': 'manager', 'show_snmp_profiles': enabled})
    assert result.status_code == 200, result.text
    assert result.json()['show_snmp_profiles'] is enabled


def test_individual_read_access_and_immediate_revocation(client, owner):
    mid, manager = user(client, owner, 'manager')
    assert client.post(PROFILES, headers=owner, json={
        'name': 'Branch', 'version': '2c', 'community': 'private-community'}).status_code == 201
    assert client.get(PROFILES, headers=manager).status_code == 403
    toggle(client, owner, mid, True)
    profiles = client.get(PROFILES, headers=manager)
    assert profiles.status_code == 200
    assert profiles.json()[0]['name'] == 'Branch'
    assert profiles.json()[0]['version'] == '2c'
    assert 'private-community' not in profiles.text and 'encrypted_credentials' not in profiles.text
    assert client.get('/api/network', headers=manager).status_code == 403
    assert client.post(PROFILES, headers=manager, json={
        'name': 'Denied', 'version': '2c', 'community': 'public'}).status_code == 403
    assert client.put('/api/users/' + mid, headers=manager,
        json={'username': 'manager', 'show_snmp_profiles': True}).status_code == 403
    token = manager['Authorization'].split()[1]
    before = live_updates.snapshot(token)
    assert before['rows']['snmp-profiles'][0]['name'] == 'Branch'
    toggle(client, owner, mid, False)
    after = live_updates.snapshot(token)
    delta = live_updates.changes(before, after)
    assert delta['user']['show_snmp_profiles'] is False
    assert delta['rows']['snmp-profiles'] == []
    assert client.get(PROFILES, headers=manager).status_code == 403
    assert client.get(PROFILES, headers=owner).status_code == 200
    client.delete('/api/users/' + mid, headers=owner).raise_for_status()
    with SessionLocal() as db:
        assert db.get(UserSNMPVisibility, mid) is None


def test_bulk_default_overrides_and_new_accounts(client, owner):
    mid, manager = user(client, owner, 'manager')
    for method in ('get', 'put'):
        kwargs = {'json': {'enabled': True}} if method == 'put' else {}
        assert getattr(client, method)(POLICY, headers=manager, **kwargs).status_code == 403
    assert client.put(POLICY, headers=owner, json={'enabled': True}).status_code == 200
    assert client.get(PROFILES, headers=manager).status_code == 200
    created = client.post('/api/users', headers=owner, json={
        'username': 'future', 'password': PASSWORD, 'role': 'manager'})
    assert created.status_code == 201 and created.json()['show_snmp_profiles'] is True
    toggle(client, owner, mid, False)
    assert client.get(PROFILES, headers=manager).status_code == 403
    # Changing another account field must keep the explicit override.
    assert client.put('/api/users/' + mid, headers=owner,
        json={'username': 'manager'}).json()['show_snmp_profiles'] is False
    assert client.put(POLICY, headers=owner, json={'enabled': True}).status_code == 200
    assert client.get(PROFILES, headers=manager).status_code == 200
    assert client.put(POLICY, headers=owner, json={'enabled': False}).status_code == 200
    assert all(row['show_snmp_profiles'] is (row['role'] == 'owner')
               for row in client.get('/api/users', headers=owner).json())
    assert client.get('/api/auth/me', headers=owner).json()['show_snmp_profiles'] is True
    assert client.get(PROFILES, headers=owner).status_code == 200


def test_explicit_hide_takes_priority_over_settings_role(client, owner):
    mid, manager = user(client, owner, 'manager')
    assert client.put('/api/users/' + mid + '/sections', headers=owner,
        json={'sections': ['settings']}).status_code == 200
    assert client.get(PROFILES, headers=manager).status_code == 200
    toggle(client, owner, mid, False)
    assert client.get(PROFILES, headers=manager).status_code == 403
    assert client.post(PROFILES, headers=manager, json={
        'name': 'Denied', 'version': '2c', 'community': 'public'}).status_code == 403


def test_visibility_migration_preserves_existing_users(client, owner):
    import importlib.util
    from pathlib import Path
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import inspect, text
    from airlink.db import engine
    from airlink.models import SNMPVisibilityDefault
    spec = importlib.util.spec_from_file_location('snmp_visibility_migration',
        Path(__file__).resolve().parents[1] / 'database/versions/19e8c92d07ba_snmp_visibility.py')
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with engine.begin() as connection:
        UserSNMPVisibility.__table__.drop(connection)
        SNMPVisibilityDefault.__table__.drop(connection)
        before = connection.execute(text('select id, username from users')).all()
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        assert {'user_snmp_visibility', 'snmp_visibility_default'} <= set(inspect(connection).get_table_names())
        assert connection.execute(text('select id, username from users')).all() == before
        migration.downgrade()
        assert connection.execute(text('select id, username from users')).all() == before
        migration.upgrade()
