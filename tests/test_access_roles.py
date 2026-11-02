import pytest
from airlink.db import SessionLocal
from airlink.models import UserManagerRole
from conftest import PASSWORD
from test_api import user, tower, device
from test_places import place


def group(client, owner, name='Support access', read=('towers',), edit=(), delete=()):
    result = client.post('/api/access-roles', headers=owner, json={
        'name': name, 'sections': list(read), 'editable_sections': list(edit), 'deletable_sections': list(delete)})
    assert result.status_code == 201, result.text
    return result.json()['id']


def role(client, owner, gid, name='Support'):
    result = client.post('/api/roles', headers=owner, json={'name': name, 'access_role_id': gid})
    assert result.status_code == 201, result.text
    return result.json()['id']


def test_role_group_permissions_apply_live_and_delete_is_separate(client, owner):
    pid = place(client, owner)
    gid = group(client, owner)
    rid = role(client, owner, gid)
    created = client.post('/api/users', headers=owner, json={'username':'staff', 'password':PASSWORD,
        'role':'manager', 'manager_role_id':rid, 'place_ids':[pid]})
    assert created.status_code == 201, created.text
    mid = created.json()['id']
    assert created.json()['manager_role_name'] == 'Support'
    assert created.json()['access_role_name'] == 'Support access'
    login = client.post('/api/auth/login', json={'username':'staff', 'password':PASSWORD})
    manager = {'Authorization':'Bearer '+login.json()['access_token']}
    tid = client.post('/api/towers', headers=owner, json={'name':'Assigned','place_id':pid}).json()['id']
    hidden = tower(client, owner, 'Hidden')
    did = device(client, owner, tid)
    assert [t['id'] for t in client.get('/api/towers', headers=manager).json()] == [tid]
    assert client.put('/api/towers/'+tid, headers=manager, json={'name':'Denied'}).status_code == 403
    assert client.delete('/api/devices/'+did, headers=manager).status_code == 403
    assert client.put('/api/users/'+mid+'/sections', headers=owner, json={'sections':['settings']}).status_code == 409
    # Edit does not grant delete.
    body = {'name':'Support access', 'sections':['towers'], 'editable_sections':['towers'], 'deletable_sections':[]}
    assert client.put('/api/access-roles/'+gid, headers=owner, json=body).status_code == 200
    assert client.put('/api/towers/'+tid, headers=manager, json={'name':'Edited'}).status_code == 200
    assert client.delete('/api/devices/'+did, headers=manager).status_code == 403
    # Delete can be granted without allowing edits, and never crosses place scope.
    body.update(editable_sections=[], deletable_sections=['towers'])
    assert client.put('/api/access-roles/'+gid, headers=owner, json=body).status_code == 200
    assert client.put('/api/towers/'+tid, headers=manager, json={'name':'Denied again'}).status_code == 403
    assert client.delete('/api/towers/'+hidden, headers=manager).status_code == 404
    assert client.delete('/api/towers/'+tid, headers=manager).status_code == 409  # still has a device
    assert client.delete('/api/devices/'+did, headers=manager).status_code == 204
    assert client.delete('/api/towers/'+tid, headers=manager).status_code == 204
    # Changing the role's group applies immediately to an existing token.
    empty = group(client, owner, 'No access', read=())
    assert client.put('/api/roles/'+rid, headers=owner, json={'name':'Support', 'access_role_id':empty}).status_code == 200
    assert client.get('/api/towers', headers=manager).status_code == 403
    assert client.get('/api/auth/me', headers=manager).json()['sections'] == []


def test_in_use_deletion_assignment_validation_and_role_cleanup(client, owner):
    mid, _ = user(client, owner, 'manager')
    gid = group(client, owner)
    rid = role(client, owner, gid)
    assigned = {'username':'manager', 'manager_role_id':rid}
    assert client.put('/api/users/'+mid, headers=owner, json=assigned).status_code == 200
    assert client.put('/api/users/'+mid, headers=owner, json={'username':'manager'}).json()['manager_role_id'] == rid
    assert client.delete('/api/roles/'+rid, headers=owner).status_code == 409
    assert client.delete('/api/access-roles/'+gid, headers=owner).status_code == 409
    assert client.put('/api/users/'+mid, headers=owner,
        json={'username':'manager', 'manager_role_id':'missing'}).status_code == 404
    assert client.put('/api/users/'+mid, headers=owner,
        json={'username':'manager', 'role':'viewer', 'manager_role_id':rid}).status_code == 422
    with SessionLocal() as db:
        assert db.get(UserManagerRole, mid).role_id == rid  # failed role change rolls back
    assert client.put('/api/users/'+mid, headers=owner,
        json={'username':'manager', 'role':'viewer'}).status_code == 200
    with SessionLocal() as db:
        assert db.get(UserManagerRole, mid) is None
    assert client.put('/api/users/'+mid, headers=owner,
        json={'username':'manager', 'role':'manager', 'manager_role_id':rid}).status_code == 200
    assert client.delete('/api/users/'+mid, headers=owner).status_code == 204
    assert client.delete('/api/roles/'+rid, headers=owner).status_code == 204
    assert client.delete('/api/access-roles/'+gid, headers=owner).status_code == 204


@pytest.mark.parametrize('account_type', ['manager', 'technician', 'viewer'])
def test_role_management_is_owner_only(client, owner, account_type):
    _, actor = user(client, owner, account_type)
    gid = group(client, owner)
    rid = role(client, owner, gid)
    for resource, identity in [('roles', rid), ('access-roles', gid)]:
        for method, path in [('GET',''), ('POST',''), ('PUT','/'+identity), ('DELETE','/'+identity)]:
            assert client.request(method, '/api/'+resource+path, headers=actor, json={}).status_code == 403


def test_group_validation_rejects_hidden_edit_delete_and_admin_escalation(client, owner):
    body = {'name':'Example', 'sections':[], 'editable_sections':[], 'deletable_sections':[]}
    for key in ('editable_sections','deletable_sections'):
        assert client.post('/api/access-roles', headers=owner, json={**body,key:['towers']}).status_code == 422
    for section in ('managers','invalid'):
        assert client.post('/api/access-roles', headers=owner, json={**body,'sections':[section]}).status_code == 422
    assert client.post('/api/access-roles', headers=owner, json={**body,'name':'  '}).status_code == 422
    assert client.post('/api/roles', headers=owner, json={'name':'Unknown','access_role_id':'missing'}).status_code == 404
    gid = group(client, owner)
    rid = role(client, owner, gid)
    assert client.post('/api/users', headers=owner, json={'username':'bad','password':PASSWORD,'role':'owner','manager_role_id':rid}).status_code == 422
    assert client.get('/api/auth/me', headers=owner).json()['manager_role_id'] is None


def test_delegated_role_permissions_are_separate_live_and_bounded(client, owner):
    mid, manager = user(client, owner, 'manager')
    url = '/api/users/'+mid+'/sections'
    grants = {'sections':['towers','roles','access_roles'], 'editable_sections':[], 'deletable_sections':[]}
    assert client.put(url, headers=owner, json=grants).status_code == 200
    gid = group(client, owner)
    rid = role(client, owner, gid)
    assert client.get('/api/roles', headers=manager).status_code == 200
    assert client.get('/api/access-roles', headers=manager).status_code == 200
    body = {'name':'Readers', 'sections':['towers'], 'editable_sections':[], 'deletable_sections':[]}
    for path, data in [('/api/access-roles', body), ('/api/roles', {'name':'New role','access_role_id':gid})]:
        assert client.post(path, headers=manager, json=data).status_code == 403
    grants['editable_sections'] = ['roles', 'access_roles']
    assert client.put(url, headers=owner, json=grants).status_code == 200
    created = client.post('/api/access-roles', headers=manager, json=body)
    assert created.status_code == 201, created.text
    created_id = created.json()['id']
    new_role = client.post('/api/roles', headers=manager, json={'name':'Delegated','access_role_id':created_id})
    assert new_role.status_code == 201
    new_id = new_role.json()['id']
    assert client.delete('/api/roles/'+new_id, headers=manager).status_code == 403
    for field, value in [('sections',['settings']), ('editable_sections',['towers']), ('deletable_sections',['towers'])]:
        assert client.put('/api/access-roles/'+created_id, headers=manager, json={**body, field:value}).status_code == 403
    powerful = group(client, owner, 'Powerful', read=('settings',), edit=('settings',))
    assert client.post('/api/roles', headers=manager, json={'name':'Escalation','access_role_id':powerful}).status_code == 403
    assert client.put('/api/access-roles/'+powerful, headers=manager, json=body).status_code == 403
    assert powerful not in [g['id'] for g in client.get('/api/roles/access-options', headers=manager).json()]
    grants.update(editable_sections=[], deletable_sections=['roles','access_roles'])
    assert client.put(url, headers=owner, json=grants).status_code == 200
    assert client.delete('/api/roles/'+new_id, headers=manager).status_code == 204
    assert client.delete('/api/access-roles/'+created_id, headers=manager).status_code == 204
    assert client.delete('/api/access-roles/'+powerful, headers=manager).status_code == 403
    assert client.put('/api/roles/'+rid, headers=manager, json={'name':'Denied','access_role_id':gid}).status_code == 403
    # Role-only access can select eligible group names but cannot open Access Roles.
    grants.update(sections=['towers','roles'], editable_sections=['roles'], deletable_sections=[])
    assert client.put(url, headers=owner, json=grants).status_code == 200
    assert client.get('/api/access-roles', headers=manager).status_code == 403
    assert gid in [g['id'] for g in client.get('/api/roles/access-options', headers=manager).json()]
    assert client.get('/api/users', headers=manager).status_code == 403
    assert client.put('/api/users/'+mid, headers=manager, json={'username':'manager','manager_role_id':rid}).status_code == 403
    assert client.put(url, headers=owner, json={'sections':[], 'editable_sections':[], 'deletable_sections':[]}).status_code == 200
    assert client.get('/api/roles', headers=manager).status_code == 403


def test_role_bound_administrator_cannot_elevate_own_access_group(client, owner):
    gid = group(client, owner, read=('access_roles',), edit=('access_roles',))
    rid = role(client, owner, gid)
    mid, manager = user(client, owner, 'manager')
    assert client.put('/api/users/'+mid, headers=owner, json={'username':'manager','manager_role_id':rid}).status_code == 200
    payload = {'name':'Attempt', 'sections':['access_roles','settings'],
               'editable_sections':['access_roles','settings'], 'deletable_sections':[]}
    assert client.put('/api/access-roles/'+gid, headers=manager, json=payload).status_code == 403
    assert client.get('/api/auth/me', headers=manager).json()['sections'] == ['access_roles']
