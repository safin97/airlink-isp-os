import asyncio
from concurrent.futures import Future
from types import SimpleNamespace

import httpx
import pytest
from airlink import device_api, registration_usernames as lookup
from airlink.db import SessionLocal
from airlink.models import SAS4UserConnection, User, Device, Metric, now
from airlink.security import cipher
from airlink.wireless_clients import username_map
from test_api import user, tower, device

MAC = 'AA:BB:CC:DD:EE:01'


def test_matching_requires_exact_mac_and_one_distinct_username():
    assert username_map([
        {'mac_address': 'aa-bb-cc-dd-ee-01', 'username': 'customer1'},
        {'mac_address': MAC, 'username': 'customer1'},
        {'mac_address': 'AA:BB:CC:DD:EE:02', 'username': 'customer2'},
        {'mac_address': 'AA:BB:CC:DD:EE:02', 'username': 'customer3'},
        {'mac_address': 'bad', 'username': 'ignored'},
        {'mac_address': 'AA:BB:CC:DD:EE:03', 'username': 'bad\nname'},
    ]) == {MAC: 'customer1', 'AA:BB:CC:DD:EE:02': None}


def test_complete_pagination_and_no_partial_matches(monkeypatch):
    def fetch(*args, page, **kwargs):
        return {'page': page, 'last_page': 2, 'clients': [
            {'mac_address': MAC, 'username': 'one' if page == 1 else 'two'}]}
    monkeypatch.setattr(lookup, 'fetch_clients', fetch)
    matches, status, _ = lookup.fetch(SimpleNamespace(username='account'), 'secret')
    assert matches == {MAC: None} and status == 'available'
    monkeypatch.setattr(lookup, 'fetch_clients', lambda *a, **kw: {
        'page': kw['page'], 'last_page': 21, 'clients': [{'mac_address': MAC, 'username': 'one'}]})
    assert lookup.fetch(SimpleNamespace(username='account'), 'secret')[:2] == ({}, 'unavailable')


class ImmediatePool:
    def submit(self, function, *args):
        result = Future()
        try:
            result.set_result(function(*args))
        except Exception as error:
            result.set_exception(error)
        return result


def test_lookup_is_cached_account_scoped_and_permission_checked(client, owner, monkeypatch):
    uid = client.get('/api/auth/me', headers=owner).json()['id']
    mid, manager = user(client, owner, 'manager')
    service = lookup.UsernameLookup()
    service.pool = ImmediatePool()
    calls = []
    def fetch(connection, password, **kwargs):
        calls.append(connection.username)
        return {'page': 1, 'last_page': 1, 'clients': [{'mac_address': MAC, 'username': connection.username}]}
    monkeypatch.setattr(lookup, 'fetch_clients', fetch)
    with SessionLocal() as db:
        for user_id, name in ((uid, 'owner-customer'), (mid, 'manager-customer')):
            db.add(SAS4UserConnection(user_id=user_id, username=name,
                encrypted_password=cipher().encrypt(b'test-secret').decode()))
        db.commit()
        account = db.get(User, uid)
        assert service.lookup(db, account)[1] == 'pending'
        assert service.lookup(db, account) == ({MAC: 'owner-customer'}, 'available')
        assert service.lookup(db, account) == ({MAC: 'owner-customer'}, 'available')
        assert calls == ['owner-customer']
        # Expired data is not reused while a new lookup is pending.
        key = next(iter(service.entries))
        expired = Future()
        stamp = lookup.time.monotonic() - 61
        expired.set_result(({MAC: 'old-customer'}, 'available', stamp))
        service.entries[key] = (expired, stamp)
        assert service.lookup(db, account) == ({}, 'pending')
        assert service.lookup(db, account)[0] == {MAC: 'owner-customer'}
        managed = db.get(User, mid)
        service.lookup(db, managed)
        assert service.lookup(db, managed) == ({MAC: 'manager-customer'}, 'available')
        db.get(SAS4UserConnection, uid).username = 'changed'
        db.commit()
        assert service.lookup(db, account)[1] == 'pending'
        assert service.lookup(db, account)[0] == {MAC: 'changed'}
    client.put('/api/users/'+mid+'/sections', headers=owner, json={'sections': ['towers']}).raise_for_status()
    with SessionLocal() as db:
        assert service.lookup(db, db.get(User, mid)) == ({}, 'not_configured')
    assert calls == ['owner-customer', 'owner-customer', 'manager-customer', 'changed']


@pytest.mark.parametrize('denied', [False, True])
def test_routeros_active_pppoe_matching_is_optional_and_excludes_other_services(denied):
    def transport(request):
        path = request.url.path
        if path == '/rest/interface/ethernet': return httpx.Response(200, json=[])
        if path == '/rest/interface/wireless/registration-table':
            return httpx.Response(200, json=[{'mac-address': MAC, 'interface': 'wlan1', 'signal-strength': '-60'}])
        if path == '/rest/ppp/active':
            assert request.url.params['.proplist'] == 'name,caller-id,service'
            if denied: return httpx.Response(403)
            return httpx.Response(200, json=[
                {'caller-id': MAC, 'name': 'subscriber1', 'service': 'pppoe', 'password': 'never-return'},
                {'caller-id': MAC, 'name': 'vpn-user', 'service': 'pptp'},
            ])
        return httpx.Response(404)
    async def collect():
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as c:
            return await device_api.routeros(c, 'https://192.0.2.1', {'api_username': 'reader', 'api_password': 'secret'}, inventory=True)
    result = asyncio.run(collect())
    assert result['wireless_registrations'][0].get('pppoe_username') == (None if denied else 'subscriber1')
    assert 'never-return' not in str(result)
    assert result['wireless_registrations'][0]['signal_dbm'] == -60


def test_endpoint_enriches_only_visible_fresh_registration_macs(client, owner, monkeypatch):
    from airlink import api
    did = device(client, owner, tower(client, owner))
    with SessionLocal() as db:
        db.get(Device, did).last_poll = now()
        db.add(Metric(device_id=did, values={'wireless_clients': 1, 'wireless_registrations': [
            {'mac_address': MAC, 'interface': 'wlan1', 'ssid': 'North', 'signal_dbm': -60}]}))
        db.commit()
    monkeypatch.setattr(api.registration_username_service, 'lookup', lambda *args: (
        {MAC: 'subscriber1', 'AA:BB:CC:DD:EE:99': 'other-tower-user'}, 'available'))
    result = client.get('/api/devices/'+did+'/wireless-clients', headers=owner)
    assert result.status_code == 200
    assert result.json()['clients'][0]['pppoe_username'] == 'subscriber1'
    assert 'other-tower-user' not in result.text
