from sqlalchemy import select
from airlink.db import SessionLocal
from airlink.models import ManagerPlace, Tower
from conftest import PASSWORD
from test_api import user, tower, device
from test_places import place


def test_place_assignment_includes_future_towers_and_revokes_moved_towers(client, owner):
    mine = place(client, owner)
    empty = place(client, owner, 'Future site')
    other = place(client, owner, 'Other')
    first = client.post('/api/towers', headers=owner, json={'name': 'First', 'place_id': mine}).json()['id']
    hidden = client.post('/api/towers', headers=owner, json={'name': 'Hidden', 'place_id': other}).json()['id']
    result = client.post('/api/users', headers=owner, json={
        'username': 'manager', 'password': PASSWORD, 'role': 'manager', 'place_ids': [mine, empty]})
    assert result.status_code == 201, result.text
    mid = result.json()['id']
    assert set(result.json()['place_ids']) == {mine, empty}
    token = client.post('/api/auth/login', json={'username': 'manager', 'password': PASSWORD}).json()['access_token']
    manager = {'Authorization': 'Bearer ' + token}
    assert {p['id'] for p in client.get('/api/places', headers=manager).json()} == {mine, empty}
    future = client.post('/api/towers', headers=owner, json={'name': 'Future', 'place_id': empty}).json()['id']
    assert {t['id'] for t in client.get('/api/towers', headers=manager).json()} == {first, future}
    did = device(client, owner, first)
    device(client, owner, hidden, '192.0.2.2')
    assert [d['id'] for d in client.get('/api/devices', headers=manager).json()] == [did]
    assert client.put('/api/towers/' + first, headers=manager, json={'name': 'Edited'}).status_code == 200
    assert client.put('/api/towers/' + first, headers=owner,
                      json={'name': 'Moved', 'place_id': other}).status_code == 200
    assert {t['id'] for t in client.get('/api/towers', headers=manager).json()} == {future}
    assert client.put('/api/towers/' + first, headers=manager, json={'name': 'Denied'}).status_code == 404
    assert client.put('/api/users/' + mid, headers=manager,
                      json={'username': 'manager', 'place_ids': [other]}).status_code == 403
    assert client.put('/api/users/' + mid, headers=owner,
                      json={'username': 'manager', 'place_ids': []}).status_code == 200
    assert client.get('/api/towers', headers=manager).json() == []


def test_legacy_assignments_preserved_until_place_selection_and_cleanup(client, owner):
    mid, manager = user(client, owner, 'manager')
    old = tower(client, owner, manager=mid)
    pid = place(client, owner)
    assert client.put('/api/towers/' + old, headers=manager, json={'name': 'Rename'}).status_code == 200
    assert client.put('/api/users/' + mid, headers=owner, json={'username': 'manager'}).status_code == 200
    assert [t['id'] for t in client.get('/api/towers', headers=manager).json()] == [old]
    url = '/api/users/' + mid
    assert client.put(url, headers=owner, json={'username': 'manager', 'place_ids': ['missing']}).status_code == 422
    with SessionLocal() as db:
        assert db.get(Tower, old).manager_id == mid
    result = client.put(url, headers=owner, json={'username': 'manager', 'place_ids': [pid, pid]})
    assert result.status_code == 200 and result.json()['place_ids'] == [pid]
    with SessionLocal() as db:
        assert db.get(Tower, old).manager_id is None
        assert db.get(ManagerPlace, (mid, pid)) is not None
    assert client.put(url, headers=owner, json={'username': 'manager', 'role': 'viewer'}).status_code == 200
    with SessionLocal() as db:
        assert db.get(ManagerPlace, (mid, pid)) is None
    assert client.put(url, headers=owner, json={'username': 'manager', 'place_ids': [pid]}).status_code == 422
    assert client.put(url, headers=owner, json={'username': 'manager', 'role': 'manager', 'place_ids': [pid]}).status_code == 200
    assert client.delete('/api/places/' + pid, headers=owner).status_code == 204
    pid = place(client, owner, 'Replacement')
    assert client.put(url, headers=owner, json={'username': 'manager', 'place_ids': [pid]}).status_code == 200
    assert client.delete(url, headers=owner).status_code == 204
    with SessionLocal() as db:
        assert db.scalar(select(ManagerPlace)) is None
