"""Permissions are checked at request time, independently of the navigation UI."""
import json
import pytest
from fastapi import HTTPException
from airlink import section_access as access, api
from airlink.db import SessionLocal
from airlink.models import User, UserSectionAccess, UserSectionEdits, UserSectionDeletes
from conftest import PASSWORD


def manager(client, owner, username='delegate', **extra):
    response = client.post('/api/users', headers=owner, json={
        'username': username, 'password': PASSWORD, 'role': 'manager', **extra})
    assert response.status_code == 201, response.text
    uid = response.json()['id']
    result = client.post('/api/auth/login', json={'username': username, 'password': PASSWORD})
    assert result.status_code == 200
    return uid, {'Authorization': 'Bearer ' + result.json()['access_token']}


def grant(client, owner, uid, view, edit=(), delete=()):
    result = client.put(f'/api/users/{uid}/sections', headers=owner, json={
        'sections': list(view), 'editable_sections': list(edit), 'deletable_sections': list(delete)})
    assert result.status_code == 200, result.text


def test_every_new_feature_defaults_off_and_has_independent_actions(client, owner):
    uid, headers = manager(client, owner)
    with SessionLocal() as db:
        user = db.get(User, uid)
        for feature in access.ADMINISTRATIVE:
            for method in ('GET', 'POST', 'DELETE'):
                with pytest.raises(HTTPException) as denied:
                    access.require_feature(user, feature, method)
                assert denied.value.status_code == 403
    for mode in ('view', 'edit', 'delete'):
        grant(client, owner, uid, access.ADMINISTRATIVE,
              access.ADMINISTRATIVE if mode == 'edit' else (),
              access.ADMINISTRATIVE if mode == 'delete' else ())
        with SessionLocal() as db:
            user = db.get(User, uid)
            for feature in access.ADMINISTRATIVE:
                for method, action in [('GET', 'view'), ('POST', 'edit'), ('DELETE', 'delete')]:
                    if action in ('view', mode):
                        access.require_feature(user, feature, method)
                    else:
                        with pytest.raises(HTTPException):
                            access.require_feature(user, feature, method)


def test_registered_api_routes_view_edit_delete_and_revocation(client, owner, monkeypatch):
    uid, headers = manager(client, owner)
    calls = []
    monkeypatch.setattr(api, 'broker', lambda command, *args: calls.append(command) or {'ok': True})
    for path in ('/api/vpn', '/api/payments/gateways', '/api/client-portal', '/api/integrations/ttlock', '/api/device-api-access'):
        assert client.get(path, headers=headers).status_code == 403
    grant(client, owner, uid, ['vpn', 'payment_gateways', 'client_portal', 'ttlock', 'device_api_access'])
    for path in ('/api/vpn', '/api/payments/gateways', '/api/client-portal', '/api/integrations/ttlock', '/api/device-api-access'):
        assert client.get(path, headers=headers).status_code == 200
    assert client.post('/api/vpn/connect', headers=headers, json={}).status_code == 403
    assert client.post('/api/vpn/delete', headers=headers, json={}).status_code == 403
    grant(client, owner, uid, ['vpn'], ['vpn'])
    assert client.post('/api/vpn/connect', headers=headers, json={}).status_code == 200
    assert client.post('/api/vpn/delete', headers=headers, json={}).status_code == 403
    grant(client, owner, uid, ['vpn'], delete=['vpn'])
    assert client.post('/api/vpn/delete', headers=headers, json={}).status_code == 200
    assert client.post('/api/vpn/connect', headers=headers, json={}).status_code == 403
    assert client.post('/api/vpn/connect', headers=headers, json={'action': 'delete'}).status_code == 403
    grant(client, owner, uid, [])
    assert client.get('/api/vpn', headers=headers).status_code == 403
    assert calls == ['vpn.status', 'vpn.connect', 'vpn.delete']


def test_delete_cannot_bypass_permissions_using_post_or_bluetooth_keys(client, owner):
    uid, headers = manager(client, owner)
    grant(client, owner, uid, ['ttlock', 'card_system'], ['ttlock', 'card_system'])
    for path, body in [
        ('/api/card-system/radius/action', {'action': 'delete', 'series': 'sample'}),
        ('/api/integrations/ttlock/mobile/prepare', {'action': 'card_delete'}),
        ('/api/integrations/ttlock/mobile/prepare', {'action': 'lock_reset'}),
        ('/api/integrations/ttlock/bridge/jobs', {'parameters': {'action': 'passcode_delete'}}),
    ]:
        assert client.post(path, headers=headers, json=body).status_code == 403
        # FastAPI also accepts JSON without a Content-Type header.
        assert client.post(path, headers=headers, content=json.dumps(body)).status_code == 403
    grant(client, owner, uid, ['ttlock'])
    assert client.get('/api/integrations/ttlock/locks/1/bluetooth', headers=headers).status_code == 403


def test_manager_admin_cannot_take_over_owner_self_or_stronger_account(client, owner):
    uid, headers = manager(client, owner)
    target_id, _ = manager(client, owner, 'other')
    grant(client, owner, uid, ['managers'], ['managers'], ['managers'])
    owner_id = client.get('/api/auth/me', headers=owner).json()['id']
    for target in (owner_id, uid, target_id):
        assert client.delete('/api/users/' + target, headers=headers).status_code == 403
        assert client.put('/api/users/' + target, headers=headers, json={
            'username': 'takeover', 'password': PASSWORD}).status_code == 403
    assert client.post('/api/users', headers=headers, json={
        'username': 'newowner', 'password': PASSWORD, 'role': 'owner'}).status_code == 403
    assert client.get('/api/users', headers=headers).json() == []


def test_manager_admin_can_assign_only_roles_within_own_grants(client, owner):
    uid, headers = manager(client, owner)
    grant(client, owner, uid, ['managers', 'ttlock'], ['managers'], ['managers'])
    roles = []
    for name, keys in [('Reader', ['ttlock']), ('Too strong', ['ttlock', 'vpn'])]:
        result = client.post('/api/access-roles', headers=owner, json={
            'name': name, 'sections': keys, 'editable_sections': [], 'deletable_sections': []})
        assert result.status_code == 201
        roles.append(result.json()['id'])
    body = {'username': 'assistant', 'password': PASSWORD, 'role': 'manager', 'access_role_id': roles[0]}
    created = client.post('/api/users', headers=headers, json=body)
    assert created.status_code == 201, created.text
    target = created.json()['id']
    assert client.put('/api/users/' + target, headers=headers, json={
        'username': 'assistant', 'access_role_id': roles[1]}).status_code == 403
    assert client.get('/api/users', headers=headers).json()[0]['access_role_id'] == roles[0]
    assert client.delete('/api/users/' + target, headers=headers).status_code == 204
