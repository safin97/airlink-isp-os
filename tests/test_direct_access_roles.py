import importlib.util
from pathlib import Path
from sqlalchemy import select
from airlink.db import SessionLocal
from airlink.models import AccessRole, UserAccessRole, ManagerRole, UserManagerRole
from conftest import PASSWORD
from test_api import user, tower
from test_access_roles import group, role


def test_all_account_types_and_direct_assignment(client, owner):
    gid = group(client, owner, 'Support', read=('towers',), edit=('towers',))
    types = client.get('/api/access-roles', headers=owner).json()
    assert {r['account_type'] for r in types if r.get('built_in')} == {'owner','manager','technician','viewer'}
    assert all(r['can_manage'] == (r['account_type'] != 'owner') for r in types if r.get('built_in'))
    created = client.post('/api/users', headers=owner, json={'username':'direct','password':PASSWORD,
        'role':'manager','access_role_id':gid})
    assert created.status_code == 201, created.text
    mid = created.json()['id']
    assert created.json()['access_role_id'] == gid
    assert created.json()['access_role_name'] == 'Support'
    assert created.json()['manager_role_id'] is None
    login = client.post('/api/auth/login', json={'username':'direct','password':PASSWORD})
    actor = {'Authorization':'Bearer '+login.json()['access_token']}
    tid = tower(client, owner, manager=mid)
    assert client.put('/api/towers/'+tid, headers=actor, json={'name':'Allowed'}).status_code == 200
    assert client.delete('/api/towers/'+tid, headers=actor).status_code == 403
    assert client.delete('/api/access-roles/'+gid, headers=owner).status_code == 409
    assert client.put('/api/users/'+mid+'/sections', headers=owner, json={'sections':[]}).status_code == 409
    assert client.put('/api/users/'+mid, headers=owner, json={'username':'direct'}).json()['access_role_id'] == gid
    changed = client.put('/api/access-roles/'+gid, headers=owner,
        json={'name':'Support','sections':[],'editable_sections':[],'deletable_sections':[]})
    assert changed.status_code == 200
    assert client.get('/api/towers', headers=actor).status_code == 403
    assert client.put('/api/users/'+mid, headers=owner,
        json={'username':'direct','role':'manager','access_role_id':None}).json()['access_role_id'] is None
    assert client.get('/api/towers', headers=actor).status_code == 200
    assert client.delete('/api/access-roles/'+gid, headers=owner).status_code == 204
    assert client.post('/api/users', headers=owner, json={'username':'invalid','password':PASSWORD,
        'role':'manager','access_role_id':'builtin:owner'}).status_code == 404


def test_consolidation_moves_role_names_and_preserves_account_permissions(client, owner):
    mid, manager = user(client, owner, 'manager')
    gid = group(client, owner, 'Network access', read=('towers','access_roles'), edit=('towers',))
    rid = role(client, owner, gid, 'Supervisor')
    assert client.put('/api/users/'+mid, headers=owner, json={'username':'manager','manager_role_id':rid}).status_code == 200
    before = client.get('/api/auth/me', headers=manager).json()
    path = Path(__file__).resolve().parents[1]/'database/versions/e29df1458b01_direct_access_roles.py'
    spec = importlib.util.spec_from_file_location('consolidate_roles', path)
    migration = importlib.util.module_from_spec(spec); spec.loader.exec_module(migration)
    with SessionLocal() as db:
        migration.consolidate(db.connection()); db.commit()
        assert db.get(UserAccessRole, mid).access_role_id == rid
        assert db.get(AccessRole, rid).name == 'Supervisor'
        assert db.scalar(select(ManagerRole)) is None
        assert db.scalar(select(UserManagerRole)) is None
        migration.consolidate(db.connection()); db.commit()
    after = client.get('/api/auth/me', headers=manager).json()
    assert after['access_role_name'] == 'Supervisor'
    for field in ('sections','editable_sections','deletable_sections','place_ids','username'):
        assert after[field] == before[field]
    assert client.delete('/api/users/'+mid, headers=owner).status_code == 204
    assert client.delete('/api/access-roles/'+rid, headers=owner).status_code == 204
