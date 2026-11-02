from sqlalchemy import select
from airlink.db import SessionLocal
from airlink.models import AuditLog, User
from test_api import user
from conftest import PASSWORD

NEW = 'New-Account-Password-497!'


def test_change_own_password_keeps_current_session_and_revokes_other_sessions(client, owner):
    uid, manager = user(client, owner, 'manager')
    other = client.post('/api/auth/login', json={'username': 'manager', 'password': PASSWORD}).json()
    other_headers = {'Authorization': 'Bearer ' + other['access_token']}
    result = client.put('/api/auth/password', headers=manager, json={
        'current_password': PASSWORD, 'new_password': NEW, 'confirm_password': NEW})
    assert result.status_code == 200, result.text
    assert client.get('/api/auth/me', headers=manager).status_code == 200
    assert client.get('/api/auth/me', headers=other_headers).status_code == 401
    assert client.post('/api/auth/refresh', headers={'X-AirLink-Request': '1'}).status_code == 401
    assert client.post('/api/auth/login', json={'username': 'manager', 'password': PASSWORD}).status_code == 401
    assert client.post('/api/auth/login', json={'username': 'manager', 'password': NEW}).status_code == 200
    assert client.get('/api/auth/me', headers=owner).status_code == 200
    with SessionLocal() as db:
        event = db.scalar(select(AuditLog).where(AuditLog.action == 'auth.password_change'))
        assert event.user_id == uid and event.target == uid
        assert NEW not in db.get(User, uid).password_hash


def test_password_change_checks_current_password_and_confirmation(client, owner):
    valid = {'current_password': PASSWORD, 'new_password': NEW, 'confirm_password': NEW}
    assert client.put('/api/auth/password', json=valid).status_code == 401
    assert client.put('/api/auth/password', headers=owner, json={**valid, 'current_password': 'wrong'}).status_code == 403
    assert client.put('/api/auth/password', headers=owner, json={**valid, 'confirm_password': 'different'}).status_code == 422
    assert client.put('/api/auth/password', headers=owner, json={**valid, 'new_password': 'short', 'confirm_password': 'short'}).status_code == 422
    assert client.put('/api/auth/password', headers=owner, json={**valid, 'user_id': 'other'}).status_code == 422
    assert client.post('/api/auth/login', json={'username': 'owner', 'password': PASSWORD}).status_code == 200


def test_viewer_can_change_only_own_password(client, owner):
    _, viewer = user(client, owner, 'viewer')
    result = client.put('/api/auth/password', headers=viewer, json={
        'current_password': PASSWORD, 'new_password': NEW, 'confirm_password': NEW})
    assert result.status_code == 200
    assert client.post('/api/auth/login', json={'username': 'viewer', 'password': NEW}).status_code == 200
    assert client.post('/api/auth/login', json={'username': 'owner', 'password': PASSWORD}).status_code == 200
