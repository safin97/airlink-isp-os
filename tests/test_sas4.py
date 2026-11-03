import json
from types import SimpleNamespace
import httpx
import pytest
from pydantic import ValidationError
from airlink import sas4
from airlink.db import SessionLocal
from airlink.models import SAS4UserConnection
from airlink.security import cipher
from test_api import user


SETTINGS = {'username': 'radius-reader', 'password': 'Sas4-Test-Only-Password'}


def test_wire_encryption_matches_openssl_vector(monkeypatch):
    monkeypatch.setattr(sas4.os, 'urandom', lambda size: bytes(size))
    assert sas4.wire_payload({'username': 'test', 'password': 'Example'}) == {
        'payload': 'U2FsdGVkX18AAAAAAAAAAEMHIsd6AIWcLukaPzRrmn48VThE3qguCCLWkgWMnijqbySy7fvMOSFkG/wMg+AM4A=='}


def test_sas4_configuration_encrypts_password_and_protects_reuse(client, owner):
    owner_id = client.get('/api/auth/me', headers=owner).json()['id']
    assert client.get('/api/integrations/sas4', headers=owner).json()['configured'] is False
    result = client.put('/api/integrations/sas4', headers=owner, json=SETTINGS)
    assert result.status_code == 200, result.text
    assert result.json()['has_password'] is True
    assert 'password' not in result.json()
    assert SETTINGS['password'] not in result.text
    with SessionLocal() as db:
        encrypted = db.get(SAS4UserConnection, owner_id).encrypted_password
        assert encrypted != SETTINGS['password']
        assert cipher().decrypt(encrypted.encode()).decode() == SETTINGS['password']
    assert client.put('/api/integrations/sas4', headers=owner, json={**SETTINGS, 'password': None}).status_code == 200
    assert client.put('/api/integrations/sas4', headers=owner, json={**SETTINGS, 'server_url': 'https://other.example', 'password': ''}).status_code == 422
    with SessionLocal() as db:
        assert db.get(SAS4UserConnection, owner_id).encrypted_password == encrypted


def test_sas4_permissions_and_connection_required(client, owner, monkeypatch):
    assert client.get('/api/integrations/sas4/clients', headers=owner).status_code == 409
    for role in ('technician', 'viewer'):
        _, headers = user(client, owner, role)
        assert client.get('/api/integrations/sas4', headers=headers).status_code == 403
        assert client.put('/api/integrations/sas4', headers=headers, json=SETTINGS).status_code == 403
        assert client.get('/api/integrations/sas4/clients', headers=headers).status_code == 403
    assert client.get('/api/integrations/sas4/clients').status_code == 401
    client.put('/api/integrations/sas4', headers=owner, json=SETTINGS)
    def fail(*args):
        raise sas4.SAS4Error('SAS4 timed out.')
    monkeypatch.setattr(sas4, 'fetch_clients', fail)
    result = client.get('/api/integrations/sas4/clients', headers=owner)
    assert result.status_code == 502
    assert SETTINGS['password'] not in result.text
    assert client.get('/api/integrations/sas4/clients?page=0', headers=owner).status_code == 422


def test_sas4_pagination_search_and_private_field_filter(monkeypatch):
    # Inspect the protocol payload separately from the OpenSSL encryption vector.
    monkeypatch.setattr(sas4, 'wire_payload', lambda payload: {'payload': json.dumps(payload)})
    requests = []
    def transport(request):
        requests.append(request)
        payload = json.loads(json.loads(request.content)['payload'])
        assert request.method == 'POST'
        if request.url.path.endswith('/login'):
            assert payload == {'username': SETTINGS['username'], 'password': SETTINGS['password']}
            return httpx.Response(200, json={'token': 'test-token'})
        assert request.url.path == '/admin/api/index.php/api/index/user'
        assert request.headers['Authorization'] == 'Bearer test-token'
        assert payload == {'page': 2, 'count': 7, 'sortBy': 'username', 'direction': 'asc', 'search': 'Ali'}
        return httpx.Response(200, json={'current_page': 2, 'per_page': 7, 'total': 101,
          'next_page_url': 'https://must-not-follow.example', 'data': [{
            'id': 3, 'username': 'ali', 'firstname': 'Ali', 'lastname': 'Test',
            'profile_details': {'name': '20 Mbps'}, 'enabled': 1, 'online_status': 1,
            'status': {'status': True}, 'parent_username': 'branch', 'static_ip': '192.0.2.5',
            'expiration': '2026-12-01', 'password': 'MUST-NOT-LEAK', 'balance': '1000',
          }]})
    result = sas4.fetch_clients(SimpleNamespace(**SETTINGS), SETTINGS['password'], page=2, search='Ali', transport=httpx.MockTransport(transport))
    assert len(requests) == 2
    assert result['last_page'] == 15 and result['page'] == 2 and result['total'] == 101
    record = result['clients'][0]
    assert record['name'] == 'Ali Test' and record['status'] == 'active • online' and record['profile'] == '20 Mbps'
    assert 'password' not in record and 'balance' not in record
    assert 'MUST-NOT-LEAK' not in json.dumps(result)


@pytest.mark.parametrize('response', [httpx.Response(401), httpx.Response(302, headers={'location': 'http://other.example'}),
    httpx.Response(200, text='<html>not JSON</html>'), httpx.Response(200, json={'token': None})])
def test_sas4_rejects_bad_login_without_following_redirect(response):
    with pytest.raises(sas4.SAS4Error):
        sas4.fetch_clients(SimpleNamespace(**SETTINGS), SETTINGS['password'], transport=httpx.MockTransport(lambda _: response))


@pytest.mark.parametrize('url', ['file:///etc/passwd', 'https://user:password@host', 'http://host/?token=secret', 'http://host/#admin'])
def test_invalid_connection_urls(url):
    with pytest.raises(ValidationError):
        sas4.ConnectionInput(**{**SETTINGS, 'server_url': url})


def test_client_status_does_not_infer_online():
    assert sas4.client_record({'username': 'a', 'status': {'status': True}})['online'] is None
    assert sas4.client_record({'username': 'a', 'enabled': 0, 'online_status': 0})['status'] == 'disabled'
    assert sas4.client_record({'username': 'a', 'enabled': 1, 'online_status': 0, 'status': {'status': False}})['status'] == 'expired / limited'


def test_managers_use_separate_connections_and_fixed_server(client, owner, monkeypatch):
    first_id, first = user(client, owner, 'manager', 'first-manager')
    second_id, second = user(client, owner, 'manager', 'second-manager')
    assert client.put('/api/integrations/sas4', headers=owner, json=SETTINGS).status_code == 200
    assert client.get('/api/integrations/sas4', headers=first).json()['configured'] is False
    assert client.get('/api/integrations/sas4/clients', headers=first).status_code == 409
    credentials = {'username': 'first-sas4', 'password': 'first-private-password'}
    assert client.put('/api/integrations/sas4', headers=first, json=credentials).status_code == 200
    assert client.get('/api/integrations/sas4', headers=second).json()['username'] == ''
    assert client.get('/api/integrations/sas4/clients', headers=second).status_code == 409
    assert client.get('/api/integrations/sas4', headers=owner).json()['username'] == SETTINGS['username']
    def fetch(connection, password, page, search):
        assert connection.user_id == first_id
        assert connection.username == credentials['username']
        assert password == credentials['password']
        return {'clients': [], 'total': 0, 'page': 1, 'last_page': 1}
    monkeypatch.setattr(sas4, 'fetch_clients', fetch)
    assert client.get('/api/integrations/sas4/clients', headers=first).status_code == 200
    assert client.put('/api/integrations/sas4', headers=first, json={**credentials, 'server_url': 'https://different.example'}).status_code == 422
    assert client.put('/api/integrations/sas4', headers=first, json={**credentials, 'user_id': second_id}).status_code == 422
    assert client.delete(f'/api/users/{first_id}', headers=owner).status_code == 204
    with SessionLocal() as db:
        assert db.get(SAS4UserConnection, first_id) is None


def test_dashboard_maps_server_totals_and_account_finance():
    requests = []
    def transport(request):
        requests.append(request)
        if request.url.path.endswith('/login'):
            return httpx.Response(200, json={'token': 'test-token'})
        assert request.method == 'GET'
        assert request.headers['Authorization'] == 'Bearer test-token'
        data = ({'total': 120, 'active': 100, 'online': 80, 'expired': 20, 'expiring_soon': 7}
                if request.url.path.endswith('/subscribers') else
                {'balance': '1250.50', 'reward_points': 42, 'private': 'MUST-NOT-LEAK'})
        return httpx.Response(200, json={'status': 200, 'data': data})
    result = sas4.fetch_dashboard(SimpleNamespace(**SETTINGS), SETTINGS['password'], transport=httpx.MockTransport(transport))
    assert len(requests) == 3
    assert {k: result[k] for k in ('total_users', 'active_users', 'online_users', 'expired_users', 'about_to_expire', 'balance', 'reward_points')} == {
        'total_users': 120, 'active_users': 100, 'online_users': 80, 'expired_users': 20,
        'about_to_expire': 7, 'balance': '1250.50', 'reward_points': 42}
    assert result['warnings'] == []
    assert 'MUST-NOT-LEAK' not in json.dumps(result)


def test_dashboard_preserves_zero_and_missing_values_when_finance_denied():
    def transport(request):
        if request.url.path.endswith('/login'):
            return httpx.Response(200, json={'token': 'test-token'})
        if request.url.path.endswith('/finance'):
            return httpx.Response(403)
        return httpx.Response(200, json={'status': 200, 'data': {'total': '0', 'active': 0}})
    result = sas4.fetch_dashboard(SimpleNamespace(**SETTINGS), SETTINGS['password'], transport=httpx.MockTransport(transport))
    assert result['total_users'] == result['active_users'] == 0
    assert result['online_users'] is None and result['balance'] is None and result['reward_points'] is None
    assert len(result['warnings']) == 1


def test_online_users_use_live_sessions_and_filter_private_fields(monkeypatch):
    monkeypatch.setattr(sas4, 'wire_payload', lambda payload: payload)
    def transport(request):
        if request.url.path.endswith('/login'):
            return httpx.Response(200, json={'token': 'test-token'})
        assert request.method == 'POST' and request.url.path.endswith('/index/online')
        payload = json.loads(request.content)
        assert payload['page'] == 2 and payload['search'] == 'Ali' and payload['count'] == 7
        return httpx.Response(200, json={'total': 75, 'per_page': 7, 'current_page': 2, 'data': [{
            'username': 'ali', 'user_profile_name': '20 Mbps', 'framedipaddress': '192.0.2.8',
            'user_details': {'firstname': 'Ali', 'lastname': 'Test', 'expiration': '2026-12-01', 'password': 'MUST-NOT-LEAK'},
            'nas_details': {'shortname': 'Tower 1', 'secret': 'MUST-NOT-LEAK'}}]})
    result = sas4.fetch_clients(SimpleNamespace(**SETTINGS), SETTINGS['password'], page=2, search='Ali', online=True, transport=httpx.MockTransport(transport))
    assert result['total'] == 75 and result['page'] == 2 and result['last_page'] == 11
    row = result['clients'][0]
    assert row['name'] == 'Ali Test' and row['ip_address'] == '192.0.2.8' and row['online'] is True
    assert row['profile'] == '20 Mbps' and row['nas'] == 'Tower 1'
    assert 'MUST-NOT-LEAK' not in json.dumps(result)


def test_dashboard_and_online_routes_are_scoped_to_signed_in_manager(client, owner, monkeypatch):
    first_id, first = user(client, owner, 'manager', 'dashboard-manager')
    _, second = user(client, owner, 'manager', 'unconfigured-manager')
    _, viewer = user(client, owner, 'viewer', 'dashboard-viewer')
    client.put('/api/integrations/sas4', headers=first, json=SETTINGS)
    def dashboard(connection, password):
        assert connection.user_id == first_id and password == SETTINGS['password']
        return {'total_users': 120}
    def online(connection, password, page, search, online):
        assert connection.user_id == first_id and password == SETTINGS['password']
        assert online and page == 2 and search == 'Ali'
        return {'clients': [], 'total': 0}
    monkeypatch.setattr(sas4, 'fetch_dashboard', dashboard)
    monkeypatch.setattr(sas4, 'fetch_clients', online)
    for route in ('dashboard', 'online?page=2&search=Ali'):
        path = '/api/integrations/sas4/' + route
        assert client.get(path, headers=first).status_code == 200
        assert client.get(path, headers=second).status_code == 409
        assert client.get(path, headers=viewer).status_code == 403
        assert client.get(path).status_code == 401


def test_user_details_and_updates_preserve_existing_values_and_hide_secrets(monkeypatch):
    monkeypatch.setattr(sas4, 'wire_payload', lambda payload: payload)
    record = {'id': 7, 'username': 'customer', 'firstname': 'First', 'lastname': 'Last',
              'phone': '123', 'expiration': '2026-12-01 12:00:00', 'profile_id': 9, 'parent_id': 3,
              'enabled': 1, 'password': 'MUST-NOT-LEAK', 'portal_password': 'MUST-NOT-LEAK', 'balance': '100'}
    writes = []
    def transport(request):
        path = request.url.path
        if path.endswith('/login'):
            return httpx.Response(200, json={'token': 'test-token'})
        if path.endswith('/auth'):
            return httpx.Response(200, json={'permissions': ['prm_users_update', 'prm_users_rename']})
        if request.method == 'GET':
            assert path.endswith('/user/7')
            return httpx.Response(200, json={'status': 200, 'data': record})
        writes.append((path, json.loads(request.content)))
        return httpx.Response(200, json={'status': 200})
    transport = httpx.MockTransport(transport)
    result = sas4.fetch_user(SimpleNamespace(**SETTINGS), SETTINGS['password'], 7, transport=transport)
    fields = {field['key']: field for field in result['fields']}
    assert list(fields) == list(sas4.VISIBLE_USER_FIELDS)
    assert fields['firstname']['value'] == 'First' and fields['phone']['editable']
    assert not fields['expiration']['editable']
    assert 'MUST-NOT-LEAK' not in json.dumps(result) and 'balance' not in fields
    changes = sas4.UserChanges(changes={'firstname': 'New', 'phone': '555', 'username': 'renamed', 'new_password': 'new-test-password'})
    result = sas4.update_user(SimpleNamespace(**SETTINGS), SETTINGS['password'], 7, changes.changes, transport=transport)
    assert result['saved']
    payload = writes[0][1]
    assert payload['firstname'] == 'New' and payload['phone'] == '555'
    assert payload['lastname'] == 'Last' and payload['profile_id'] == 9 and payload['parent_id'] == 3
    assert 'password' not in payload and 'portal_password' not in payload and 'expiration' not in payload
    assert writes[1][0].endswith('/user/rename/7') and writes[1][1] == {'new_username': 'renamed'}
    assert writes[2][0].endswith('/user/password') and writes[2][1]['user_id'] == 7


def test_user_edit_denied_before_any_write():
    def transport(request):
        if request.url.path.endswith('/login'):
            return httpx.Response(200, json={'token': 'test-token'})
        assert request.method == 'GET'
        return httpx.Response(200, json={'permissions': ['prm_users_update']})
    with pytest.raises(sas4.HTTPException) as exc:
        sas4.update_user(SimpleNamespace(**SETTINGS), SETTINGS['password'], 7,
            {'expiration': '2026-12-01 00:00:00'}, transport=httpx.MockTransport(transport))
    assert exc.value.status_code == 403


@pytest.mark.parametrize('active,permission,profile,allowed', [
    (False, False, 12, True), (True, True, 12, True),
    (True, False, 12, False), (False, False, 99, False),
])
def test_service_profile_uses_dedicated_action_and_checks_access(monkeypatch, active, permission, profile, allowed):
    monkeypatch.setattr(sas4, 'wire_payload', lambda payload: payload)
    permissions = ['prm_users_change_profile']
    if permission:
        permissions.append('prm_users_change_profile_active')
    writes = []
    def handle(request):
        path = request.url.path
        if path.endswith('/login'):
            return httpx.Response(200, json={'token': 'test-token'})
        if path.endswith('/auth'):
            return httpx.Response(200, json={'permissions': permissions})
        if path.endswith('/user/7'):
            return httpx.Response(200, json={'status': 200, 'data': {
                'id': 7, 'username': 'customer', 'profile_id': 9, 'status': {'expiration': active}}})
        if path.endswith('/list/profile/0'):
            return httpx.Response(200, json={'data': [{'id': 12, 'name': 'New service'}]})
        writes.append((path, json.loads(request.content)))
        return httpx.Response(200, json={'status': 200})
    transport = httpx.MockTransport(handle)
    details = sas4.fetch_user(SimpleNamespace(**SETTINGS), SETTINGS['password'], 7, transport=transport)
    field = next(f for f in details['fields'] if f['key'] == 'profile_id')
    assert field['editable'] == (not active or permission)
    if allowed:
        result = sas4.update_user(SimpleNamespace(**SETTINGS), SETTINGS['password'], 7,
                                 {'profile_id': profile}, transport=transport)
        assert result['saved_fields'] == ['profile_id']
        assert len(writes) == 1 and writes[0][0].endswith('/user/changeProfile')
        assert writes[0][1] == {'user_id': 7, 'profile_id': 12, 'change_type': 'immediate'}
    else:
        with pytest.raises(sas4.HTTPException):
            sas4.update_user(SimpleNamespace(**SETTINGS), SETTINGS['password'], 7,
                             {'profile_id': profile}, transport=transport)
        assert not writes


@pytest.mark.parametrize('changes', [{'balance': 100}, {'expiration': '2026-02-31 00:00:00'},
    {'static_ip': 'invalid'}, {'username': '../escape'}, {'enabled': 5}, {'profile_id': 0}])
def test_invalid_user_edits_rejected(changes):
    with pytest.raises(ValidationError):
        sas4.UserChanges(changes=changes)


def test_online_profile_uses_user_id_not_session_id():
    result = sas4.online_record({'id': 900, 'radacctid': 900, 'username': 'customer', 'user_details': {'id': 7}})
    assert result['id'] == 7 and result['session_id'] == 900


def test_user_details_routes_use_own_connection_and_restrict_roles(client, owner, monkeypatch):
    manager_id, manager = user(client, owner, 'manager', 'user-editor')
    _, other = user(client, owner, 'manager', 'no-sas4')
    _, viewer = user(client, owner, 'viewer', 'read-only')
    client.put('/api/integrations/sas4', headers=manager, json=SETTINGS)
    def fetch(connection, password, user_id):
        assert connection.user_id == manager_id and user_id == 7
        assert password == SETTINGS['password']
        return {'id': 7, 'fields': []}
    def update(connection, password, user_id, changes):
        fetch(connection, password, user_id)
        assert changes == {'firstname': 'New'}
        return {'saved': True}
    monkeypatch.setattr(sas4, 'fetch_user', fetch)
    monkeypatch.setattr(sas4, 'update_user', update)
    path = '/api/integrations/sas4/users/7'
    assert client.get(path, headers=manager).status_code == 200
    assert client.put(path, headers=manager, json={'changes': {'firstname': 'New'}}).status_code == 200
    for headers, status in [(other, 409), (viewer, 403), ({}, 401)]:
        assert client.get(path, headers=headers).status_code == status
        assert client.put(path, headers=headers, json={'changes': {'firstname': 'New'}}).status_code == status


def test_partial_user_save_does_not_report_success(monkeypatch):
    monkeypatch.setattr(sas4, 'wire_payload', lambda payload: payload)
    def transport(request):
        if request.url.path.endswith('/login'):
            return httpx.Response(200, json={'token': 'test-token'})
        if request.url.path.endswith('/auth'):
            return httpx.Response(200, json={'permissions': ['prm_users_update', 'prm_users_rename']})
        if request.method == 'GET':
            return httpx.Response(200, json={'status': 200, 'data': {'id': 7, 'username': 'old'}})
        return httpx.Response(200, json={'status': 200 if request.method == 'PUT' else 400})
    with pytest.raises(sas4.SAS4Error, match='Some changes were saved'):
        sas4.update_user(SimpleNamespace(**SETTINGS), SETTINGS['password'], 7,
            {'firstname': 'New', 'username': 'duplicate'}, transport=httpx.MockTransport(transport))


@pytest.mark.parametrize('service,online,expected', [
    ({'status': True, 'expiration': True}, False, 'active'),
    ({'status': True, 'expiration': True}, True, 'active • online'),
    ({'status': False, 'expiration': False}, False, 'expired'),
    ({'status': False, 'expiration': False}, True, 'expired • online'),
    ({'status': False, 'expiration': True}, True, 'limited • online'),
    (None, True, 'online'),
    (None, None, 'unknown'),
])
def test_user_status_retains_expiry_and_connection(service, online, expected):
    result = sas4.client_record({'username': 'customer', 'enabled': 1, 'online_status': online, 'status': service})
    assert result['status'] == expected
    if online is True:
        result = sas4.online_record({'username': 'customer', 'status': service, 'user_details': {'id': 7, 'enabled': 1}})
        assert result['status'] == expected


def test_online_disabled_user_is_not_shown_as_active():
    result = sas4.client_record({'username': 'customer', 'enabled': 0, 'online_status': 1,
        'status': {'status': True, 'expiration': True}})
    assert result['status'] == 'disabled • online'


def test_card_recharge_uses_card_method_and_scoped_permissions(monkeypatch):
    monkeypatch.setattr(sas4, 'wire_payload', lambda payload: payload)
    writes = []
    def transport(request):
        path = request.url.path
        if path.endswith('/login') and request.method == 'POST':
            return httpx.Response(200, json={'token': 'test-token'})
        if path.endswith('/auth'):
            return httpx.Response(200, json={'permissions': ['prm_users_activate', 'prm_users_activate_card']})
        if path.endswith('/resources/login'):
            return httpx.Response(200, json={'status': 200, 'data': {'site_currency': 'IQD'}})
        if path.endswith('/user/7'):
            return httpx.Response(200, json={'status': 200, 'data': {'id': 7, 'username': 'customer'}})
        if '/activationData/' in path:
            return httpx.Response(200, json={'status': 200, 'data': {'username': 'customer', 'profile_name': '20 Mbps',
                'user_expiration': '2026-11-01', 'units': 1, 'user_price': 100, 'manager_balance': 'PRIVATE'}})
        assert path.endswith('/user/activate') and request.method == 'POST'
        writes.append(json.loads(request.content))
        return httpx.Response(200, json={'status': 200})
    transport = httpx.MockTransport(transport)
    info = sas4.fetch_recharge(SimpleNamespace(**SETTINGS), SETTINGS['password'], 7, transport=transport)
    assert len(info['transaction_id']) == 32 and 'PRIVATE' not in json.dumps(info)
    assert not writes
    data = sas4.CardRecharge(pin='TEST-PIN', transaction_id=info['transaction_id'])
    result = sas4.redeem_card(SimpleNamespace(**SETTINGS), SETTINGS['password'], 7, data, transport=transport)
    assert result == {'recharged': True}
    assert len(writes) == 1 and writes[0]['method'] == 'card' and writes[0]['user_id'] == 7
    assert writes[0]['pin'] == 'TEST-PIN' and writes[0]['transaction_id'] == info['transaction_id']
    assert writes[0]['money_collected'] == 0 and writes[0]['issue_invoice'] == 0
    assert 'TEST-PIN' not in json.dumps(result)


def test_recharge_permissions_checked_before_activation():
    def transport(request):
        if request.url.path.endswith('/login'):
            return httpx.Response(200, json={'token': 'test-token'})
        assert request.url.path.endswith('/auth') and request.method == 'GET'
        return httpx.Response(200, json={'permissions': ['prm_users_update']})
    with pytest.raises(sas4.HTTPException) as exc:
        sas4.redeem_card(SimpleNamespace(**SETTINGS), SETTINGS['password'], 7,
            sas4.CardRecharge(pin='TEST-PIN', transaction_id='a' * 32), transport=httpx.MockTransport(transport))
    assert exc.value.status_code == 403


@pytest.mark.parametrize('outcome', ['success', 'unknown'])
def test_recharge_prevents_duplicate_submissions(client, owner, monkeypatch, outcome):
    calls = []
    def redeem(connection, password, user_id, data):
        assert connection.user_id == client.get('/api/auth/me', headers=owner).json()['id']
        calls.append(data.transaction_id)
        if outcome == 'unknown':
            raise sas4.SAS4Error('Recharge was not confirmed. Check SAS4 before trying again.')
        return {'recharged': True}
    monkeypatch.setattr(sas4, 'redeem_card', redeem)
    client.put('/api/integrations/sas4', headers=owner, json=SETTINGS)
    body = {'pin': 'TEST-PRIVATE-PIN', 'transaction_id': 'b' * 32}
    path = '/api/integrations/sas4/users/7/recharge'
    first = client.post(path, headers=owner, json=body)
    second = client.post(path, headers=owner, json=body)
    assert first.status_code == (200 if outcome == 'success' else 502)
    assert second.status_code == (200 if outcome == 'success' else 409)
    assert len(calls) == 1
    assert body['pin'] not in first.text + second.text
    _, viewer = user(client, owner, 'viewer', 'recharge-viewer')
    assert client.post(path, headers=viewer, json=body).status_code == 403
    assert client.get(path, headers=viewer).status_code == 403


def test_card_recharge_rejects_blank_pin_and_payment_method_override():
    for body in [{'pin': ' ', 'transaction_id': 'a' * 32}, {'pin': 'test', 'transaction_id': 'bad'},
                 {'pin': 'test', 'transaction_id': 'a' * 32, 'method': 'credit'}]:
        with pytest.raises(ValidationError):
            sas4.CardRecharge(**body)


def recharge_transport(monkeypatch, writes, cost=2000):
    monkeypatch.setattr(sas4, 'wire_payload', lambda data: data)
    def handler(request):
        path = request.url.path
        if path.endswith('/login') and request.method == 'POST':
            return httpx.Response(200, json={'token': 'test-token'})
        if path.endswith('/auth'):
            return httpx.Response(200, json={'permissions': ['prm_users_activate', 'prm_users_activate_credit', 'prm_users_extend']})
        if path.endswith('/user/7'):
            return httpx.Response(200, json={'status': 200, 'data': {'id': 7, 'username': 'customer', 'profile_id': 3, 'expiration': '2026-12-01 00:00:00'}})
        if '/activationData/' in path:
            return httpx.Response(200, json={'status': 200, 'data': {'profile_name': '20 Mbps', 'n_required_amount': cost, 'user_price': 2500, 'units': 1}})
        if path.endswith('/resources/login'):
            return httpx.Response(200, json={'data': {'site_currency': 'IQD'}})
        if path.endswith('/allowedExtensions/3'):
            return httpx.Response(200, json={'status': 200, 'data': [{'id': 12, 'name': 'Other'}, {'id': 11, 'name': 'Test'}]})
        if path.endswith('/profile/11'):
            return httpx.Response(200, json={'status': 200, 'data': {'id': 11, 'name': 'Test', 'price': 0, 'vat': '0', 'expiration_amount': 1, 'expiration_unit': 2}})
        assert request.method == 'POST'
        writes.append((path, json.loads(request.content)))
        return httpx.Response(200, json={'status': 200})
    return httpx.MockTransport(handler)


def test_test_extension_auto_selection_and_balance_activation(monkeypatch):
    writes = []
    transport = recharge_transport(monkeypatch, writes)
    quote = sas4.fetch_recharge(SimpleNamespace(**SETTINGS), SETTINGS['password'], 7, transport=transport)
    assert quote['extension']['name'] == 'Test' and quote['extension']['id'] == 11
    assert quote['extension']['cost'] == '0' and not writes
    assert quote['manager_cost'] == '2000' and quote['currency'] == 'IQD'
    for method, cost in [('credit', '2000'), ('extend', '0')]:
        data = sas4.CardRecharge(method=method, transaction_id='d' * 32, expected_cost=cost,
            expected_profile_id=3, expected_expiration='2026-12-01 00:00:00', extension_id=11 if method == 'extend' else None)
        assert sas4.redeem_card(SimpleNamespace(**SETTINGS), SETTINGS['password'], 7, data, transport=transport)['recharged']
    assert writes[0][0].endswith('/user/activate') and writes[0][1]['method'] == 'credit'
    assert writes[1][0].endswith('/user/extend') and writes[1][1]['profile_id'] == 11
    assert writes[1][1]['method'] == 'credit'


def test_changed_cost_or_unallowed_extension_never_charges(monkeypatch):
    writes = []
    transport = recharge_transport(monkeypatch, writes)
    for method, cost, extension in [('credit', '1', None), ('extend', '0', 99)]:
        data = sas4.CardRecharge(method=method, transaction_id='d' * 32, expected_cost=cost, expected_profile_id=3, extension_id=extension)
        with pytest.raises(sas4.HTTPException):
            sas4.redeem_card(SimpleNamespace(**SETTINGS), SETTINGS['password'], 7, data, transport=transport)
    assert not writes


def test_resolve_online_username_uses_own_account_and_exact_match(client, owner, monkeypatch):
    _, manager = user(client, owner, 'manager', 'resolve-manager')
    _, other = user(client, owner, 'manager', 'unconnected-manager')
    _, viewer = user(client, owner, 'viewer', 'resolve-viewer')
    client.put('/api/integrations/sas4', headers=manager, json=SETTINGS).raise_for_status()
    calls = []
    def fetch(connection, password, page, search, count):
        assert connection.username == SETTINGS['username'] and password == SETTINGS['password']
        assert search == 'customer' and count == 100
        calls.append(page)
        return {'clients':[{'id':900,'username':'another-customer'}] if page == 1 else
                [{'id':7,'username':'customer','password':'never-expose'}], 'last_page':2}
    monkeypatch.setattr(sas4, 'fetch_clients', fetch)
    path = '/api/integrations/sas4/resolve-user?username=customer'
    response = client.get(path, headers=manager)
    assert response.status_code == 200 and response.json() == {'id':7,'username':'customer'}
    assert calls == [1,2] and 'never-expose' not in response.text
    for headers,status in [(other,409),(viewer,403),({},401)]:
        assert client.get(path,headers=headers).status_code == status
    monkeypatch.setattr(sas4,'fetch_clients',lambda *args,**kwargs: {'clients':[{'id':900,'username':'customer-other'}],'last_page':1})
    assert client.get(path,headers=manager).status_code == 404
    monkeypatch.setattr(sas4,'fetch_clients',lambda *args,**kwargs: {'clients':[{'id':None,'username':'customer'}],'last_page':1})
    assert client.get(path,headers=manager).status_code == 502
