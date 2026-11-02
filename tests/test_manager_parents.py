from conftest import PASSWORD


def create(client, owner, name, **extra):
    response = client.post('/api/users', headers=owner, json={
        'username': name, 'password': PASSWORD, 'role': 'manager', **extra})
    assert response.status_code == 201, response.text
    return response.json()


def change(client, owner, account, **extra):
    return client.put('/api/users/' + account['id'], headers=owner,
                      json={'username': account['username'], **extra})


def test_parent_create_edit_remove_preserves_access(client, owner):
    parent = create(client, owner, 'parent')
    child = create(client, owner, 'child', parent_id=parent['id'])
    assert child['parent_id'] == parent['id'] and child['parent_username'] == 'parent'
    assert child['place_ids'] == []
    original_sections = child['sections']
    renamed = change(client, owner, child, username='renamed').json()
    assert renamed['parent_id'] == parent['id']
    assert renamed['sections'] == original_sections
    replacement = create(client, owner, 'replacement')
    result = change(client, owner, renamed, parent_id=replacement['id'])
    assert result.status_code == 200 and result.json()['parent_username'] == 'replacement'
    result = change(client, owner, renamed, parent_id=None)
    assert result.status_code == 200 and result.json()['parent_id'] is None
    assert result.json()['sections'] == original_sections


def test_parent_rejects_self_cycles_invalid_and_nonmanager(client, owner):
    a = create(client, owner, 'a')
    b = create(client, owner, 'b', parent_id=a['id'])
    c = create(client, owner, 'c', parent_id=b['id'])
    for parent_id in [a['id'], b['id'], c['id'], 'missing']:
        assert change(client, owner, a, parent_id=parent_id).status_code == 422
    viewer = create(client, owner, 'viewer', role='viewer')
    assert change(client, owner, a, parent_id=viewer['id']).status_code == 422
    assert change(client, owner, viewer, parent_id=a['id']).status_code == 422
    assert client.post('/api/users/' + c['id'] + '/disable', headers=owner).status_code == 200
    assert change(client, owner, b, parent_id=c['id']).status_code == 422
    rows = {r['id']: r for r in client.get('/api/users', headers=owner).json()}
    assert rows[a['id']]['parent_id'] is None
    assert rows[b['id']]['parent_id'] == a['id']


def test_parent_delete_and_role_change_keep_children(client, owner):
    a = create(client, owner, 'a')
    b = create(client, owner, 'b', parent_id=a['id'])
    c = create(client, owner, 'c', parent_id=b['id'])
    assert change(client, owner, b, role='viewer').status_code == 200
    rows = {r['id']: r for r in client.get('/api/users', headers=owner).json()}
    assert rows[b['id']]['parent_id'] is None and rows[c['id']]['parent_id'] is None
    assert change(client, owner, c, parent_id=a['id']).status_code == 200
    assert client.delete('/api/users/' + a['id'], headers=owner).status_code == 204
    rows = {r['id']: r for r in client.get('/api/users', headers=owner).json()}
    assert rows[c['id']]['parent_id'] is None


def test_manager_cannot_change_hierarchy_or_inherit_places(client, owner):
    place = client.post('/api/places', headers=owner, json={'name': 'Private site'}).json()['id']
    parent = create(client, owner, 'parent', place_ids=[place])
    child = create(client, owner, 'child', parent_id=parent['id'])
    token = client.post('/api/auth/login', json={'username': 'child', 'password': PASSWORD}).json()['access_token']
    auth = {'Authorization': 'Bearer ' + token}
    assert change(client, auth, child, parent_id=None).status_code == 403
    assert client.get('/api/places', headers=auth).json() == []
