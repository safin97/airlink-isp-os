from sqlalchemy import select
from airlink.db import SessionLocal
from airlink.models import User, Tower, Device, LoginSession, AuditLog
from airlink.security import verify_password
from test_api import user, tower, device
from conftest import PASSWORD


def test_manager_username_and_password_update_revokes_sessions(client, owner):
    mid, manager = user(client, owner, 'manager')
    result = client.put(f'/api/users/{mid}', headers=owner, json={'username': 'renamed', 'password': ''})
    assert result.status_code == 200, result.text
    assert 'password_hash' not in result.json()
    assert result.json()['role'] == 'manager'
    assert client.get('/api/auth/me', headers=manager).status_code == 401
    assert client.post('/api/auth/refresh', headers={'X-AirLink-Request': '1'}).status_code == 401
    login = client.post('/api/auth/login', json={'username': 'renamed', 'password': PASSWORD})
    assert login.status_code == 200
    changed_password = 'Manager-New-Password-937!'
    assert client.put(f'/api/users/{mid}', headers=owner,
        json={'username': 'renamed', 'password': changed_password}).status_code == 200
    assert client.post('/api/auth/login', json={'username': 'renamed', 'password': PASSWORD}).status_code == 401
    assert client.post('/api/auth/login', json={'username': 'renamed', 'password': changed_password}).status_code == 200
    with SessionLocal() as db:
        assert verify_password(changed_password, db.get(User, mid).password_hash)
        assert changed_password not in str([(x.action, x.target) for x in db.scalars(select(AuditLog))])


def test_delete_manager_preserves_inventory_and_audits(client, owner):
    mid, manager = user(client, owner, 'manager')
    tid = tower(client, owner, manager=mid)
    did = device(client, owner, tid)
    result = client.delete(f'/api/users/{mid}', headers=owner)
    assert result.status_code == 204, result.text
    assert client.get('/api/auth/me', headers=manager).status_code == 401
    assert client.post('/api/auth/refresh', headers={'X-AirLink-Request': '1'}).status_code == 401
    assert client.post('/api/auth/login', json={'username': 'manager', 'password': PASSWORD}).status_code == 401
    with SessionLocal() as db:
        assert db.get(User, mid) is None
        assert db.get(Tower, tid).manager_id is None
        assert db.get(Device, did) is not None
        assert db.scalar(select(LoginSession).where(LoginSession.user_id == mid)) is None
        assert db.scalar(select(AuditLog).where(AuditLog.action == 'user.delete')).target == f'{mid}:manager'
        assert db.scalar(select(AuditLog).where(AuditLog.action == 'auth.login', AuditLog.user_id.is_(None))) is not None


def test_manager_edits_require_owner_and_validate_credentials(client, owner):
    mid, manager = user(client, owner, 'manager')
    oid = client.get('/api/auth/me', headers=owner).json()['id']
    url = f'/api/users/{mid}'
    assert client.put(url, headers=manager, json={'username': 'new'}).status_code == 403
    assert client.delete(url, headers=manager).status_code == 403
    assert client.delete(url).status_code == 401
    assert client.put(f'/api/users/{oid}', headers=owner, json={'username': 'new'}).status_code == 409
    assert client.delete(f'/api/users/{oid}', headers=owner).status_code == 409
    assert client.put(url, headers=owner, json={'username': 'manager', 'password': 'short'}).status_code == 422
    assert client.put(url, headers=owner, json={'username': 'has spaces'}).status_code == 422
    assert client.put(url, headers=owner, json={'username': 'manager', 'role': 'owner'}).status_code == 422
    assert client.put(url, headers=owner, json={'username': 'owner'}).status_code == 409
    assert client.get('/api/auth/me', headers=manager).status_code == 200
    assert client.get('/api/auth/me', headers=manager).json()['username'] == 'manager'


def test_technician_and_viewer_accounts_can_be_edited_and_deleted(client, owner):
    for role in ('technician', 'viewer'):
        uid, credentials = user(client, owner, role)
        tid = tower(client, owner, name=role)
        did = device(client, owner, tid, ip='192.0.2.31' if role == 'technician' else '192.0.2.32')
        if role == 'technician':
            assert client.put(f'/api/users/{uid}/devices/{did}', headers=owner).status_code == 200
        result = client.put(f'/api/users/{uid}', headers=owner, json={'username': role + '-renamed'})
        assert result.status_code == 200, result.text
        assert result.json()['role'] == role
        assert client.delete(f'/api/users/{uid}', headers=owner).status_code == 204
        assert client.get('/api/auth/me', headers=credentials).status_code == 401
        with SessionLocal() as db:
            assert db.get(Device, did) is not None
            assert db.get(User, uid) is None


def test_role_changes_clear_old_assignments_and_revoke_sessions(client, owner):
    from airlink.models import DeviceAssignment
    mid, manager = user(client, owner, 'manager')
    tid = tower(client, owner, manager=mid)
    did = device(client, owner, tid)
    result = client.put(f'/api/users/{mid}', headers=owner, json={'username': 'manager', 'role': 'technician'})
    assert result.status_code == 200, result.text
    assert result.json()['role'] == 'technician'
    assert client.get('/api/auth/me', headers=manager).status_code == 401
    with SessionLocal() as db:
        assert db.get(Tower, tid).manager_id is None
        assert db.get(Device, did) is not None
    login = client.post('/api/auth/login', json={'username': 'manager', 'password': PASSWORD})
    assert login.status_code == 200 and login.json()['user']['role'] == 'technician'
    tech = {'Authorization': 'Bearer ' + login.json()['access_token']}
    assert client.put(f'/api/users/{mid}/devices/{did}', headers=owner).status_code == 200
    assert client.put(f'/api/users/{mid}', headers=tech, json={'username': 'manager', 'role': 'manager'}).status_code == 403
    assert client.put(f'/api/users/{mid}', headers=owner, json={'username': 'manager', 'role': 'viewer'}).status_code == 200
    assert client.get('/api/auth/me', headers=tech).status_code == 401
    with SessionLocal() as db:
        assert db.scalar(select(DeviceAssignment).where(DeviceAssignment.user_id == mid)) is None
    assert client.put(f'/api/users/{mid}', headers=owner, json={'username': 'manager', 'role': 'manager'}).status_code == 200
    assert client.put(f'/api/users/{mid}', headers=owner, json={'username': 'manager', 'role': 'invalid'}).status_code == 422
