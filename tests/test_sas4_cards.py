"""Direct SAS4 cards: account scoping, permissions, safe output and mutation contract."""
from contextlib import contextmanager
import json
import httpx
import pytest
from airlink import sas4
from test_api import user
from test_sas4 import SETTINGS


@pytest.fixture
def radius(client, owner, monkeypatch):
    client.put('/api/integrations/sas4', headers=owner, json=SETTINGS)
    calls = []
    state = {'permissions': ['prm_cards_index', 'prm_cards_download', 'prm_cards_suspend_release',
                             'prm_cards_change_owner', 'prm_cards_delete'], 'status': 200}
    monkeypatch.setattr(sas4, 'wire_payload', lambda data: data)
    @contextmanager
    def session(connection, password):
        assert connection.username == SETTINGS['username']
        assert password == SETTINGS['password']
        def handler(request):
            path = request.url.path.removeprefix(sas4.API_PATH)
            body = json.loads(request.content) if request.content else None
            calls.append((request.method, path, body))
            if path == 'auth':
                return httpx.Response(200, json={'permissions': state['permissions']})
            if path.startswith('index/'):
                return httpx.Response(200, json={'data': [{
                    'series': 'SERIES-1', 'qty': 100, 'used': 5, 'suspended': 0,
                    'owner_details': {'username': 'branch', 'password': 'PRIVATE-OWNER'},
                    'id': 42, 'pin': 'SECRET-PIN', 'password': 'SECRET-PASSWORD',
                    'serialnumber': 'CARD-42', 'user_details': {'username': 'customer'},
                    'token': 'SECRET-TOKEN',
                }], 'total': 51, 'current_page': 2, 'per_page': 25})
            if state.get('timeout'):
                raise httpx.ReadTimeout('timeout', request=request)
            return httpx.Response(200, json={'status': state['status']})
        try:
            with httpx.Client(transport=httpx.MockTransport(handler)) as remote:
                yield remote, {}
        except httpx.HTTPError as exc:
            raise sas4.SAS4Error('Transport failure') from exc
    monkeypatch.setattr(sas4, 'sas4_session', session)
    return calls, state


def test_series_uses_saved_connection_and_hides_pins(client, owner, radius):
    calls, _ = radius
    response = client.get('/api/card-system/radius?page=2&search=SERIES&manager_id=7', headers=owner)
    assert response.status_code == 200
    data = response.json()
    assert data['total'] == 51 and data['last_page'] == 3
    assert data['rows'][0]['owner_details.username'] == 'branch'
    assert data['actions']['suspend'] and not data['actions']['expiry']
    assert calls[-1] == ('POST', 'index/series', {'page': 2, 'count': 25,
        'sortBy': 'series_date', 'direction': 'desc', 'search': 'SERIES', 'parent_id': 7,
        'type': -1, 'profile_id': -1})
    assert 'SECRET' not in response.text and 'PRIVATE' not in response.text
    assert response.headers['cache-control'] == 'no-store'


def test_cards_disclose_only_on_explicit_reveal(client, owner, radius):
    response = client.get('/api/card-system/radius/cards?series=SERIES-1', headers=owner)
    assert response.status_code == 200 and 'SECRET' not in response.text
    response = client.get('/api/card-system/radius/cards?series=SERIES-1&reveal=true', headers=owner)
    assert response.json()['rows'][0]['pin'] == 'SECRET-PIN'
    assert 'SECRET-TOKEN' not in response.text and 'PRIVATE-OWNER' not in response.text
    assert response.headers['cache-control'] == 'no-store'
    radius[1]['permissions'].remove('prm_cards_download')
    assert client.get('/api/card-system/radius/cards?series=SERIES-1&reveal=true', headers=owner).status_code == 403


@pytest.mark.parametrize('operation,path,body', [
    ({'action': 'suspend'}, 'series/suspend/SERIES-1', None),
    ({'action': 'release'}, 'series/release/SERIES-1', None),
    ({'action': 'delete'}, 'series/delete/SERIES-1', None),
    ({'action': 'owner', 'owner_id': 8}, 'series/changeOwner', {'series': ['SERIES-1'], 'owner': 8}),
    ({'action': 'expiry', 'expiration': '2027-05-12'}, 'series/changeExpiry', {'series': ['SERIES-1'], 'new_expiry': '2027-05-12'}),
])
def test_mutations_match_sas4_ui_and_require_permissions(client, owner, radius, operation, path, body):
    calls, state = radius
    state['permissions'].append('prm_managers_sysadmin')
    response = client.post('/api/card-system/radius/action', headers=owner, json={'series': 'SERIES-1', **operation})
    assert response.status_code == 200 and response.json() == {'ok': True}
    assert calls[-1] == ('POST' if body else 'GET', path, body)
    calls.clear()
    state['permissions'] = ['prm_cards_index']
    assert client.post('/api/card-system/radius/action', headers=owner, json={'series': 'SERIES-1', **operation}).status_code == 403
    assert len(calls) == 1 and calls[0][1] == 'auth'


def test_owner_only_validation_and_no_get_mutations(client, owner, radius):
    _, manager = user(client, owner, 'manager', 'radius-manager')
    assert client.get('/api/card-system/radius', headers=manager).status_code == 403
    assert client.post('/api/card-system/radius/action', headers=manager, json={'series': 'SERIES-1', 'action': 'suspend'}).status_code == 403
    for payload in [
        {'series': '../auth', 'action': 'suspend'},
        {'series': 'SERIES-1', 'action': 'owner'},
        {'series': 'SERIES-1', 'action': 'expiry'},
        {'series': 'SERIES-1', 'action': 'suspend', 'owner_id': 7},
    ]:
        assert client.post('/api/card-system/radius/action', headers=owner, json=payload).status_code == 422
    assert client.get('/api/card-system/radius/action', headers=owner).status_code == 405
    assert radius[0] == []


@pytest.mark.parametrize('timeout', [False, True])
def test_uncertain_change_is_not_retried_or_reported_success(client, owner, radius, timeout):
    calls, state = radius
    state.update(status=500, timeout=timeout)
    response = client.post('/api/card-system/radius/action', headers=owner, json={'series': 'SERIES-1', 'action': 'suspend'})
    assert response.status_code == 502
    assert 'Refresh' in response.json()['detail']
    assert sum(path.startswith('series/') for _, path, _ in calls) == 1
