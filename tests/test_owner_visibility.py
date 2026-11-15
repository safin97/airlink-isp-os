from airlink import live_updates, section_access
from test_api import user, tower

PATH = '/api/access-roles/builtin:owner/visibility'


def test_owner_can_hide_and_restore_pages_without_losing_administration(client, owner):
    _, other_owner = user(client, owner, 'owner', name='second_owner')
    before = client.get('/api/auth/me', headers=owner).json()
    assert set(before['visible_sections']) == set(section_access.OWNER_PAGES)
    row = next(r for r in client.get('/api/access-roles', headers=owner).json() if r['account_type'] == 'owner')
    assert row['can_manage'] and not row['can_delete'] and row['visibility_only']
    result = client.put(PATH, headers=owner, json={'visible_sections': []})
    assert result.status_code == 200, result.text
    assert set(result.json()['visible_sections']) == set(section_access.OWNER_PINNED)
    for headers in (owner, other_owner):
        identity = client.get('/api/auth/me', headers=headers).json()
        assert set(identity['visible_sections']) == set(section_access.OWNER_PINNED)
        for field in ('sections', 'editable_sections', 'deletable_sections'):
            assert identity[field] == list(section_access.ALL)
        assert client.get('/api/users', headers=headers).status_code == 200
    assert tower(client, owner)
    assert client.delete('/api/access-roles/builtin:owner', headers=owner).status_code == 403
    restored = client.put(PATH, headers=other_owner, json={'visible_sections': list(section_access.OWNER_PAGES)})
    assert restored.status_code == 200
    assert client.get('/api/auth/me', headers=owner).json()['visible_sections'] == list(section_access.OWNER_PAGES)


def test_owner_visibility_is_owner_only_and_validates_input(client, owner):
    uid, manager = user(client, owner, 'manager')
    assert client.put('/api/users/'+uid+'/sections', headers=owner,
                      json={'sections': ['access_roles'], 'editable_sections': ['access_roles']}).status_code == 200
    assert client.put(PATH, headers=manager, json={'visible_sections': []}).status_code == 403
    assert client.put(PATH, json={'visible_sections': []}).status_code == 401
    for payload in ({'visible_sections': ['unknown']}, {'visible_sections': 'dashboard'},
                    {'visible_sections': [], 'editable_sections': []}):
        assert client.put(PATH, headers=owner, json=payload).status_code == 422
    assert client.get('/api/auth/me', headers=owner).json()['visible_sections'] == list(section_access.OWNER_PAGES)


def test_visibility_changes_reach_live_owner_sessions(client, owner):
    token = owner['Authorization'].removeprefix('Bearer ')
    before = live_updates.snapshot(token)
    result = client.put(PATH, headers=owner, json={'visible_sections': ['diagnostics', 'diagnostics']})
    assert result.status_code == 200
    after = live_updates.snapshot(token)
    delta = live_updates.changes(before, after)
    assert set(delta['user']['visible_sections']) == {'diagnostics', *section_access.OWNER_PINNED}
    assert len(delta['user']['visible_sections']) == 3
    assert delta['user']['sections'] == list(section_access.ALL)
    assert 'users' in after['rows']
    assert next(r for r in delta['rows']['access-roles'] if r['account_type'] == 'owner')['visible_sections'] == delta['user']['visible_sections']
