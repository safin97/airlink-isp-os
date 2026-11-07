import asyncio
import json
from unittest.mock import AsyncMock

import pytest
from pysnmp.proto.rfc1905 import NoSuchInstance
from sqlalchemy import select

from airlink.db import SessionLocal
from airlink.models import Device, SNMPProfile, now
from airlink.security import cipher
from monitoring import snmp
from test_api import user, tower


@pytest.mark.parametrize('version', ['1', '2c'])
def test_community_encrypted_and_not_returned(client, owner, version):
    data = {'name': 'Radio profile', 'version': version, 'community': 'private-read-only-lab'}
    response = client.post('/api/snmp-profiles', headers=owner, json=data)
    assert response.status_code == 201, response.text
    assert response.json()['version'] == version
    listing = client.get('/api/snmp-profiles', headers=owner)
    assert listing.json()[0]['version'] == version
    for result in (response, listing):
        assert data['community'] not in result.text
        assert 'encrypted_credentials' not in result.text
    with SessionLocal() as db:
        profile = db.scalar(select(SNMPProfile))
        assert data['community'] not in profile.encrypted_credentials
        assert json.loads(cipher().decrypt(profile.encrypted_credentials.encode())) == {
            'version': version, 'community': data['community']}
    _, manager = user(client, owner, 'manager')
    assert client.get('/api/snmp-profiles', headers=manager).status_code == 403
    assert client.post('/api/snmp-profiles', headers=manager, json=data).status_code == 403


@pytest.mark.parametrize('credentials', [
    {'version': '2c'}, {'version': '1', 'community': '   '},
    {'version': '3', 'community': 'lab'},
    {'version': '2c', 'community': 'lab', 'username': 'mixed'},
])
def test_invalid_profile_rejected(client, owner, credentials):
    assert client.post('/api/snmp-profiles', headers=owner,
                       json={'name': 'Invalid', **credentials}).status_code == 422


def test_legacy_v3_profile_still_lists(client, owner):
    with SessionLocal() as db:
        db.add(SNMPProfile(name='Legacy', encrypted_credentials=cipher().encrypt(json.dumps({
            'username': 'old', 'auth_key': 'legacy-auth-key', 'priv_key': 'legacy-priv-key'}).encode()).decode()))
        db.commit()
    assert client.get('/api/snmp-profiles', headers=owner).json()[0]['version'] == '3'


@pytest.mark.parametrize('vendor', ['mikrotik', 'ubiquiti_m5', 'ubiquiti_ac', 'mimosa'])
def test_vendor_device_accepted(client, owner, vendor):
    tid = tower(client, owner)
    result = client.post('/api/devices', headers=owner, json={
        'name': 'Radio', 'ip_address': '192.0.2.2', 'tower_id': tid, 'vendor': vendor})
    assert result.status_code == 201, result.text
    assert result.json()['vendor'] == vendor


def test_mimosa_v2c_device_add_and_edit_preserve_settings_and_hide_credentials(client, owner):
    tid = tower(client, owner)
    credentials = [
        {'name': 'Mimosa tower read', 'version': '2c', 'community': 'mimosa-read-only-lab'},
        {'name': 'Mimosa replacement read', 'version': '2c', 'community': 'mimosa-replacement-lab'},
    ]
    responses = [client.post('/api/snmp-profiles', headers=owner, json=data) for data in credentials]
    for response in responses:
        assert response.status_code == 201, response.text
        assert response.json()['version'] == '2c'
    profile_ids = [response.json()['id'] for response in responses]
    payload = {
        'name': 'Mimosa sector radio', 'ip_address': '192.0.2.20', 'tower_id': tid,
        'vendor': 'mimosa', 'model': 'C5c', 'snmp_profile_id': profile_ids[0],
        'poll_interval': 120, 'retries': 4, 'failure_threshold': 6, 'cpu_threshold': 85,
        'enabled': True,
    }
    created = client.post('/api/devices', headers=owner, json=payload)
    assert created.status_code == 201, created.text
    device_id = created.json()['id']
    for key, value in payload.items():
        assert created.json()[key] == value

    with SessionLocal() as db:
        device = db.get(Device, device_id)
        device.last_poll = now()
        device.status = 'online'
        device.failures = 2
        db.commit()

    replacement = {**payload, 'snmp_profile_id': profile_ids[1]}
    edited = client.put('/api/devices/' + device_id, headers=owner, json=replacement)
    assert edited.status_code == 200, edited.text
    for key, value in replacement.items():
        assert edited.json()[key] == value
    listing = client.get('/api/devices', headers=owner)
    assert len(listing.json()) == 1
    assert listing.json()[0]['snmp_profile_id'] == profile_ids[1]
    assert listing.json()[0]['snmp_status'] == 'pending'
    profiles = client.get('/api/snmp-profiles', headers=owner)
    for response in [*responses, created, edited, listing, profiles]:
        assert 'encrypted_credentials' not in response.text
        for data in credentials:
            assert data['community'] not in response.text
    with SessionLocal() as db:
        device = db.get(Device, device_id)
        assert device.last_poll is None and device.status == 'unknown' and device.failures == 0
        for profile_id, data in zip(profile_ids, credentials):
            encrypted = db.get(SNMPProfile, profile_id).encrypted_credentials
            assert data['community'] not in encrypted
            assert json.loads(cipher().decrypt(encrypted.encode())) == {
                'version': '2c', 'community': data['community']}


def test_authentication_versions():
    assert snmp.authentication({'version': '1', 'community': 'lab'}).message_processing_model == 0
    assert snmp.authentication({'version': '2c', 'community': 'lab'}).message_processing_model == 1
    assert snmp.authentication({'version': '2', 'community': 'lab'}).message_processing_model == 1
    assert isinstance(snmp.authentication({'username': 'old', 'auth_key': 'old-auth-secret',
                                          'priv_key': 'old-priv-secret'}), snmp.UsmUserData)
    with pytest.raises(ValueError):
        snmp.authentication({'version': 'unsupported'})


def test_unavailable_textual_table_not_used(monkeypatch):
    async def walk(*args, **kwargs):
        yield None, 0, 0, [('1.2.3.1', NoSuchInstance())]
    monkeypatch.setattr(snmp, 'walk_cmd', walk)
    assert asyncio.run(snmp.read_table(None, None, None, '1.2.3', textual=True)) == {}


@pytest.mark.parametrize('version', ['1', '2c', '3'])
@pytest.mark.parametrize('vendor', ['mikrotik', 'ubiquiti_m5', 'ubiquiti_ac', 'mimosa', 'generic'])
def test_collection_standard_fallback_and_vendor_metrics(monkeypatch, version, vendor):
    requested = []
    family = 'ubiquiti' if vendor.startswith('ubiquiti') else vendor
    values = {
        snmp.TABLES['if_name']: {'2': 'ether2'},
        snmp.TABLES['if_status']: {'1': 1, '2': 1},
        snmp.TABLES['if_type']: {'1': 71, '2': 6},
        snmp.FALLBACK_TABLES['if_descr']: {'1': 'wlan1'},
        snmp.FALLBACK_TABLES['if_speed']: {'1': 100_000_000, '2': 100_000_000},
        snmp.FALLBACK_TABLES['if_rx32']: {'1': 123, '2': 456},
        snmp.FALLBACK_TABLES['if_tx32']: {'1': 789, '2': 987},
        snmp.TABLES['if_rx_octets']: {'2': 2**35},
        snmp.TABLES['if_tx_octets']: {'2': 2**36},
    }
    for key, oid in snmp.WIRELESS_TABLES.get(family, {}).items():
        values[oid] = {'1': {'client_count': 0, 'frequency_mhz': 5805,
                            'signal_dbm': -64, 'noise_dbm': -96}[key]}
    async def table(engine, auth, target, oid, textual=False):
        requested.append(oid)
        return values.get(oid, {})
    monkeypatch.setattr(snmp, 'read_table', table)
    monkeypatch.setattr(snmp.UdpTransportTarget, 'create', AsyncMock(return_value=object()))
    monkeypatch.setattr(snmp, 'get_cmd', AsyncMock(return_value=(None, 0, 0, [(snmp.UPTIME, 12300)])))
    credentials = {'version': version, 'community': 'lab'} if version != '3' else {
        'version': version, 'username': 'lab', 'auth_key': 'lab-auth-secret', 'priv_key': 'lab-priv-secret'}
    result = asyncio.run(snmp.collect('192.0.2.1', credentials, 0, vendor=vendor))
    assert result['uptime_seconds'] == 123
    assert result['interfaces']['1'] == {'name': 'wlan1', 'type': 71, 'status': 1, 'speed_mbps': 100,
                                       'counter_bits': 32, 'rx_octets': 123, 'tx_octets': 789}
    assert result['interfaces']['2']['type'] == 6
    assert result['interfaces']['2']['counter_bits'] == (32 if version == '1' else 64)
    if version == '1':
        assert snmp.TABLES['if_rx_octets'] not in requested
        assert snmp.TABLES['if_tx_octets'] not in requested
    assert 'cpu_percent' not in result and 'memory_percent' not in result
    if vendor in ('generic', 'mimosa'):
        assert 'wireless_clients' not in result and 'wireless' not in result
    else:
        assert result['wireless_clients'] == 0
        assert result['weakest_signal_dbm'] == -64
        assert result['radio_frequencies_mhz'] == [5805]


def test_legacy_rates_reject_ambiguous_wraps_and_counter_changes():
    old = {'rx_octets': 100, 'counter_bits': 32, 'speed_mbps': 100}
    current = {**old, 'rx_octets': 850}
    assert snmp.interface_rate(old, current, 'rx', 60) == 100
    assert snmp.interface_rate(old, {**current, 'speed_mbps': 1000}, 'rx', 60) is None
    assert snmp.interface_rate(old, {**current, 'speed_mbps': None}, 'rx', 60) is None
    assert snmp.interface_rate(old, {**current, 'rx_octets': 50}, 'rx', 60) is None
    assert snmp.interface_rate(old, {**current, 'counter_bits': 64}, 'rx', 60) is None
    assert snmp.interface_rate(old, current, 'rx', 60, rebooted=True) is None
    assert snmp.interface_rate(old, {**current, 'discontinuity': 100}, 'rx', 60) is None
    assert snmp.interface_rate({'rx_octets': 100}, {'rx_octets': 850}, 'rx', 60) == 100


def test_v3_protocol_selection_and_legacy_defaults(client, owner):
    credentials = {'username':'reader','auth_key':'auth-key-123','priv_key':'priv-key-123'}
    legacy = snmp.authentication(credentials)
    assert legacy.authentication_protocol == snmp.USM_AUTH_HMAC192_SHA256
    for auth, constant in [('SHA1',snmp.USM_AUTH_HMAC96_SHA), ('MD5',snmp.USM_AUTH_HMAC96_MD5), ('SHA256',snmp.USM_AUTH_HMAC192_SHA256)]:
        selected = snmp.authentication({**credentials,'auth_protocol':auth,'priv_protocol':'AES128'})
        assert selected.authentication_protocol == constant
    result = client.post('/api/snmp-profiles', headers=owner, json={
        'name':'RouterOS v3', 'version':'3', **credentials, 'auth_protocol':'SHA1', 'priv_protocol':'AES128'})
    assert result.status_code == 201, result.text
    assert client.post('/api/snmp-profiles', headers=owner, json={
        'name':'Invalid', 'version':'2c','community':'public','auth_protocol':'SHA1'}).status_code == 422


def test_v2_alias_is_saved_as_community_protocol(client, owner):
    response = client.post('/api/snmp-profiles', headers=owner,
                           json={'name': 'MikroTik v2', 'version': '2', 'community': 'public'})
    assert response.status_code == 201
    assert response.json()['version'] == '2c'


@pytest.mark.parametrize('bulk_fails', [False, True])
def test_v2_bulk_walk_and_legacy_getnext_fallback(monkeypatch, bulk_fails):
    calls = []
    async def bulk(*args, **kwargs):
        calls.append('bulk')
        assert args[4:6] == (0, 10)
        if bulk_fails:
            yield None, 5, 0, []
        else:
            yield None, 0, 0, [('1.2.3.1', 1000), ('1.2.3.2', 100)]
    async def walk(*args, **kwargs):
        calls.append('next')
        yield None, 0, 0, [('1.2.3.1', 1000)]
    monkeypatch.setattr(snmp, 'bulk_walk_cmd', bulk)
    monkeypatch.setattr(snmp, 'walk_cmd', walk)
    result = asyncio.run(snmp.read_table(None, snmp.authentication({'version':'2c','community':'public'}), None, '1.2.3'))
    assert result['1'] == 1000
    assert calls == (['bulk', 'next'] if bulk_fails else ['bulk'])


def test_mikrotik_station_signal_ssid_and_ether1(monkeypatch):
    from airlink.client_telemetry import snmp_readings
    requested = []
    async def table(engine, auth, target, oid, textual=False):
        requested.append(oid)
        if oid == snmp.TABLES['if_name']: return {'1':'ether1','2':'ether2'}
        if oid == snmp.TABLES['if_type']: return {'1':6,'2':6}
        if oid == snmp.TABLES['if_status']: return {'1':1,'2':1}
        if oid == snmp.TABLES['if_speed_mbps']: return {'1':1000,'2':100}
        if oid == snmp.STATION_TABLES['mikrotik']['station_signal_dbm']: return {'3':-58}
        if oid == snmp.STATION_TABLES['mikrotik']['ssid']:
            assert textual
            return {'3':'AirLink test'}
        return {}
    monkeypatch.setattr(snmp, 'read_table', table)
    monkeypatch.setattr(snmp.UdpTransportTarget, 'create', AsyncMock(return_value=object()))
    monkeypatch.setattr(snmp, 'get_cmd', AsyncMock(return_value=(None, 0, 0, [(snmp.UPTIME, 100)])))
    values = asyncio.run(snmp.collect('192.0.2.1', {'version':'2','community':'public'}, 0, vendor='mikrotik', link_only=True))
    assert snmp_readings(values) == {'ethernet_links':[{'name':'ether1','speed_mbps':1000}],
                                    'signal_dbm':-58, 'ssid':'AirLink test'}
    assert snmp.WIRELESS_TABLES['mikrotik']['signal_dbm'] not in requested
    values['wireless']['station_signal_dbm']['4'] = -80
    values['wireless']['ssid']['4'] = 'Other radio'
    assert snmp_readings(values)['signal_dbm'] is None
    assert snmp_readings(values)['ssid'] is None
