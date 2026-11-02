from airlink.db import SessionLocal
from airlink.models import TowerPlace
from test_api import user, tower


def place(client, owner, name='Zakho'):
    response = client.post('/api/places', headers=owner, json={'name': name})
    assert response.status_code == 201, response.text
    return response.json()['id']


def test_place_tower_lifecycle_and_legacy_updates(client, owner):
    pid = place(client, owner)
    assert client.get('/api/places', headers=owner).json()[0]['tower_count'] == 0
    tid = client.post('/api/towers', headers=owner, json={'name':'North','place_id':pid}).json()['id']
    assert client.get('/api/towers', headers=owner).json()[0]['place_id'] == pid
    assert client.get('/api/places', headers=owner).json()[0]['tower_count'] == 1
    assert client.delete('/api/places/'+pid, headers=owner).status_code == 409
    assert client.put('/api/places/'+pid, headers=owner, json={'name':'Zakho Center'}).status_code == 200
    # Older clients that omit placement must not unassign the tower.
    saved = client.put('/api/towers/'+tid, headers=owner, json={'name':'Renamed'})
    assert saved.status_code == 200 and saved.json()['place_id'] == pid
    saved = client.put('/api/towers/'+tid, headers=owner, json={'name':'Renamed','place_id':None})
    assert saved.status_code == 200 and saved.json()['place_id'] is None
    assert client.delete('/api/places/'+pid, headers=owner).status_code == 204
    assert client.get('/api/towers', headers=owner).json()[0]['id'] == tid


def test_scoped_places_and_owner_control(client, owner):
    mid, manager = user(client, owner, 'manager')
    _, viewer = user(client, owner, 'viewer')
    mine = place(client, owner)
    hidden = place(client, owner, 'Other')
    tid = client.post('/api/towers', headers=owner, json={'name':'My tower','place_id':mine,'manager_id':mid}).json()['id']
    client.post('/api/towers', headers=owner, json={'name':'Hidden tower','place_id':mine})
    assert client.get('/api/places', headers=manager).json() == [{'id':mine,'name':'Zakho','tower_count':1}]
    for actor in (manager, viewer):
        assert client.post('/api/places', headers=actor, json={'name':'Denied'}).status_code == 403
        assert client.put('/api/places/'+mine, headers=actor, json={'name':'Denied'}).status_code == 403
        assert client.delete('/api/places/'+hidden, headers=actor).status_code == 403
    result = client.put('/api/towers/'+tid, headers=manager, json={'name':'My tower','manager_id':mid,'place_id':hidden})
    assert result.status_code == 403
    assert client.get('/api/towers', headers=manager).json()[0]['place_id'] == mine
    assert client.delete('/api/towers/'+tid, headers=owner).status_code == 204
    with SessionLocal() as db:
        assert db.get(TowerPlace, tid) is None


def test_place_validation_and_existing_towers(client, owner):
    tid = tower(client, owner)
    assert client.get('/api/towers', headers=owner).json()[0]['place_id'] is None
    assert client.post('/api/places', headers=owner, json={'name':'   '}).status_code == 422
    pid = place(client, owner)
    assert client.post('/api/places', headers=owner, json={'name':' Zakho '}).status_code == 409
    assert client.put('/api/towers/'+tid, headers=owner, json={'name':'North','place_id':'missing'}).status_code == 404
    assert client.put('/api/towers/'+tid, headers=owner, json={'name':'North','place_id':pid}).status_code == 200
    assert client.get('/api/places').status_code == 401
