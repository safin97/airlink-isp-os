from copy import deepcopy
import pytest
from starlette.websockets import WebSocketDisconnect
from airlink import live_updates
from test_api import user, tower


def token(headers):
    return headers['Authorization'].removeprefix('Bearer ')


def test_live_frames_are_scoped_and_only_include_changes(client, owner):
    mid, manager = user(client, owner, 'manager')
    tid = tower(client, owner, manager=mid)
    tower(client, owner, name='Private tower')
    before = live_updates.snapshot(token(manager))
    assert [r['id'] for r in before['rows']['towers']] == [tid]
    assert 'users' not in before['rows']
    assert 'access-roles' not in before['rows']
    assert 'snmp-profiles' not in before['rows']
    same = deepcopy(before)
    same['summary']['observed_at'] = 'different timestamp'
    assert live_updates.changes(before, same) == {'type':'heartbeat'}
    assert client.put('/api/towers/'+tid, headers=owner, json={'name':'Changed live'}).status_code == 200
    after = live_updates.snapshot(token(manager))
    delta = live_updates.changes(before, after)
    assert delta['rows']['towers'][0]['name'] == 'Changed live'
    assert 'devices' not in delta['rows']
    assert 'user' not in delta
    assert client.put('/api/users/'+mid+'/sections',headers=owner,json={'sections':[]}).status_code == 200
    restricted = live_updates.snapshot(token(manager))
    delta = live_updates.changes(after, restricted)
    assert delta['rows']['towers'] == []
    assert delta['summary'] == {}
    assert delta['user']['sections'] == []
    assert restricted['rows'] == {}


def test_live_socket_authentication_snapshot_and_revocation(client, owner, monkeypatch):
    monkeypatch.setattr(live_updates, 'INTERVAL', .01)
    with client.websocket_connect('/api/live') as ws:
        ws.send_json({'token':token(owner)})
        first = ws.receive_json()
        assert first['type'] == 'snapshot'
        assert first['user']['role'] == 'owner'
        assert 'password_hash' not in str(first)
        client.post('/api/auth/logout', headers=owner)
        with pytest.raises(WebSocketDisconnect) as error:
            for _ in range(20): ws.receive_json()
        assert error.value.code == 4401
    with client.websocket_connect('/api/live') as ws:
        ws.send_json({'token':'invalid'})
        with pytest.raises(WebSocketDisconnect) as error:
            ws.receive_json()
        assert error.value.code == 4401


def test_configured_viewer_cannot_receive_hidden_resources(client, owner):
    _, viewer = user(client, owner, 'viewer')
    assert client.put('/api/access-roles/builtin:viewer', headers=owner,
        json={'name':'Limited viewer','sections':['alerts'],'editable_sections':[], 'deletable_sections':[]}).status_code == 200
    data = live_updates.snapshot(token(viewer))
    assert set(data['rows']) == {'alerts'}
    assert data['summary'] == {}
