import asyncio
import json
from unittest.mock import AsyncMock

import pytest
from pysnmp.proto.rfc1905 import NoSuchInstance
from sqlalchemy import select

from airlink.db import SessionLocal
from airlink.models import SNMPProfile
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
    {'version': '2', 'community': 'lab'}, {'version': '3', 'community': 'lab'},
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


@pytest.mark.parametrize('vendor', ['mikrotik', 'ubiquiti_m5', 'ubiquiti_ac'])
def test_vendor_device_accepted(client, owner, vendor):
    tid = tower(client, owner)
    result = client.post('/api/devices', headers=owner, json={
        'name': 'Radio', 'ip_address': '192.0.2.2', 'tower_id': tid, 'vendor': vendor})
    assert result.status_code == 201, result.text
    assert result.json()['vendor'] == vendor


def test_authentication_versions():
    assert snmp.authentication({'version': '1', 'community': 'lab'}).message_processing_model == 0
    assert snmp.authentication({'version': '2c', 'community': 'lab'}).message_processing_model == 1
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
@pytest.mark.parametrize('vendor', ['mikrotik', 'ubiquiti_m5', 'ubiquiti_ac', 'generic'])
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
    if vendor == 'generic':
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
