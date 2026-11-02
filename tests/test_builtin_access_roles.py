import pytest
from airlink.db import SessionLocal
from airlink.models import BuiltinAccessRole
from conftest import PASSWORD
from test_api import user, tower
from test_access_roles import group


@pytest.mark.parametrize('kind', ['manager', 'technician', 'viewer'])
def test_system_type_edit_applies_to_existing_accounts_and_delete_requires_reassignment(client, owner, kind):
    uid, actor = user(client, owner, kind)
    tid = tower(client, owner, manager=uid if kind == 'manager' else None)
    url = '/api/access-roles/builtin:' + kind
    data = {'name': 'Updated ' + kind, 'sections': ['dashboard', 'towers'],
            'editable_sections': [], 'deletable_sections': []}
    changed = client.put(url, headers=owner, json=data)
    assert changed.status_code == 200, changed.text
    identity = client.get('/api/auth/me', headers=actor).json()
    assert identity['access_role_name'] == data['name']
    assert identity['access_policy_configured'] is True
    assert set(identity['sections']) == {'dashboard', 'towers'}
    assert identity['editable_sections'] == []
    assert client.get('/api/reports/availability.csv', headers=actor).status_code == 403
    assert client.put('/api/towers/'+tid, headers=actor, json={'name': 'Forbidden'}).status_code == 403
    assert client.delete(url, headers=owner).status_code == 409
    # Grant edit and delete separately; existing scopes are still enforced.
    data['editable_sections'] = ['towers']
    assert client.put(url, headers=owner, json=data).status_code == 200
    expected = 404 if kind == 'technician' else 200
    assert client.put('/api/towers/'+tid, headers=actor, json={'name': 'Allowed'}).status_code == expected
    assert client.delete('/api/towers/'+tid, headers=actor).status_code == 403
    assert client.put('/api/access-roles/builtin:owner', headers=owner, json=data).status_code == 403
    assert client.delete('/api/access-roles/builtin:owner', headers=owner).status_code == 403
    gid = group(client, owner, 'Replacement')
    reassigned = client.put('/api/users/'+uid, headers=owner,
        json={'username': kind, 'role': 'manager', 'access_role_id': gid})
    assert reassigned.status_code == 200, reassigned.text
    assert client.delete(url, headers=owner).status_code == 204
    for _ in range(2):
        assert not any(row['id'] == 'builtin:'+kind for row in client.get('/api/access-roles', headers=owner).json())
    with SessionLocal() as db:
        assert db.get(BuiltinAccessRole, kind).deleted is True
    assert client.post('/api/users', headers=owner,
        json={'username': 'deleted-type', 'password': PASSWORD, 'role': kind}).status_code == 422
    assert client.put('/api/users/'+uid, headers=owner,
        json={'username': kind, 'role': kind, 'access_role_id': None}).status_code == 422
    assert client.put(url, headers=owner, json=data).status_code == 404


def test_builtin_policy_never_overrides_custom_role_and_only_owner_can_change_defaults(client, owner):
    uid, actor = user(client, owner, 'manager')
    gid = group(client, owner, 'Delegated', read=('access_roles',), edit=('access_roles',), delete=('access_roles',))
    assert client.put('/api/users/'+uid, headers=owner,
        json={'username': 'manager', 'access_role_id': gid}).status_code == 200
    data = {'name': 'Limited manager', 'sections': [], 'editable_sections': [], 'deletable_sections': []}
    assert client.put('/api/access-roles/builtin:manager', headers=actor, json=data).status_code == 403
    assert client.delete('/api/access-roles/builtin:viewer', headers=actor).status_code == 403
    assert client.put('/api/access-roles/builtin:manager', headers=owner, json=data).status_code == 200
    assert client.get('/api/auth/me', headers=actor).json()['sections'] == ['access_roles']
    assert client.delete('/api/access-roles/builtin:manager', headers=owner).status_code == 204
    # The manager security boundary is still valid for custom types.
    assert client.post('/api/users', headers=owner,
        json={'username': 'custom-manager', 'password': PASSWORD, 'role': 'manager', 'access_role_id': gid}).status_code == 201
