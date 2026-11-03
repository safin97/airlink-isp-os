import asyncio
from unittest.mock import AsyncMock
import pytest
from airlink import online_device, online_device_auto as auto, snmp_discovery
from airlink.device_management import ManagementError
from monitoring import snmp
from test_online_device import MANUAL, QUERY, PATH, CHANGE, setup_login

CONFIG = {'transport': 'auto', 'protocol': 'both', 'verify_tls': True,
          'api_username': 'reader', 'api_password': 'private-device-password', 'snmp_community': 'private-read'}
FINGERPRINT = 'SHA256:' + 'a' * 43


@pytest.mark.parametrize('vendor,version', [('mikrotik', '1'), ('ubiquiti_m5', '2c')])
def test_customer_detection_uses_both_versions_without_tower_filters(monkeypatch, vendor, version):
    monkeypatch.setattr(snmp.UdpTransportTarget, 'create', AsyncMock(return_value=object()))
    calls = []
    async def get(engine, auth, target, context, *oids, **kwargs):
        calls.append(auth.message_processing_model)
        if version == '2c' and auth.message_processing_model == 0:
            return 'timeout', 0, 0, []
        oid, description = ('1.3.6.1.4.1.14988.1', 'RouterOS') if vendor == 'mikrotik' else ('1.3.6.1.4.1.41112.1', 'Ubiquiti NanoStation M5')
        return (None, 0, 0, [('oid', oid), ('description', description)]) if len(oids) == 2 else (None, 0, 0, [('name', 'Radio')])
    monkeypatch.setattr(snmp, 'get_cmd', get)
    result = asyncio.run(auto.detect_vendor('10.2.3.4', 'private-read'))
    assert result['vendor'] == vendor and result['snmp_version'] == version
    assert calls == ([0, 0] if version == '1' else [0, 1, 1])
    assert 'private-read' not in str(result)


def test_unknown_snmp_v1_identity_continues_to_v2(monkeypatch):
    monkeypatch.setattr(snmp.UdpTransportTarget, 'create', AsyncMock(return_value=object()))
    async def get(engine, auth, target, context, *oids, **kwargs):
        if auth.message_processing_model == 0:
            return None, 0, 0, [('oid', '1.3.6.1.4.1.99'), ('desc', 'Unknown')]
        return (None, 0, 0, [('oid', '1.3.6.1.4.1.14988.1'), ('desc', 'RouterOS')]) if len(oids) == 2 else (None, 0, 0, [('name', 'Router')])
    monkeypatch.setattr(snmp, 'get_cmd', get)
    assert asyncio.run(auto.detect_vendor('10.2.3.4', 'public'))['vendor'] == 'mikrotik'


def test_mikrotik_connections_are_sequential_stop_at_success_and_keep_resolved_transport(monkeypatch):
    monkeypatch.setattr(auto, 'detect_vendor', AsyncMock(return_value={'vendor': 'mikrotik', 'snmp_version': '2c'}))
    calls, running = [], []
    async def collect(address, config, transport):
        assert not running
        running.append(True)
        await asyncio.sleep(0)
        running.clear()
        calls.append((config['transport'], config.get('protocol')))
        assert config['api_password'] == CONFIG['api_password']
        if config['transport'] != 'routeros':
            raise OSError('No supported service')
        return {'vendor': 'MikroTik', 'settings': []}
    monkeypatch.setattr(online_device, 'collect_once', collect)
    result = asyncio.run(online_device.collect('10.2.3.4', CONFIG))
    assert calls == [('web', 'https'), ('routeros_tls', 'both'), ('web', 'http'), ('routeros', 'both')]
    assert result['connection']['transport'] == 'routeros'
    assert result['snmp_version'] == '2'
    assert len(result['connection_attempts']) == 4
    assert 'private' not in str(result)


def test_ubiquiti_ssh_trust_does_not_prevent_available_web_login(monkeypatch):
    monkeypatch.setattr(auto, 'detect_vendor', AsyncMock(return_value={'vendor': 'ubiquiti_ac', 'snmp_version': '1'}))
    calls = []
    async def collect(address, config, transport):
        calls.append(config['transport'])
        if config['transport'] == 'airos_ssh':
            if config.get('ssh_fingerprint'):
                return {'vendor': 'Ubiquiti', 'settings': [], 'restart_on_save': True}
            return {'requires_trust': True, 'ssh_fingerprint': FINGERPRINT}
        return {'vendor': 'Ubiquiti', 'web_url': 'https://10.2.3.4'}
    monkeypatch.setattr(online_device, 'collect_once', collect)
    first = asyncio.run(online_device.collect('10.2.3.4', CONFIG))
    assert calls == ['airos_ssh', 'web']
    assert first['connection']['transport'] == 'web' and first['ssh_upgrade_fingerprint'] == FINGERPRINT
    calls.clear()
    second = asyncio.run(online_device.collect('10.2.3.4', {**CONFIG, 'ssh_fingerprint': FINGERPRINT}))
    assert calls == ['airos_ssh'] and second['restart_on_save']
    assert second['connection']['ssh_fingerprint'] == FINGERPRINT


def test_ssh_key_change_never_falls_back(monkeypatch):
    monkeypatch.setattr(auto, 'detect_vendor', AsyncMock(return_value={'vendor': 'ubiquiti', 'snmp_version': '1'}))
    calls = []
    async def collect(*args):
        calls.append(True)
        raise ManagementError('SSH host key changed', 409)
    monkeypatch.setattr(online_device, 'collect_once', collect)
    with pytest.raises(ManagementError):
        asyncio.run(online_device.collect('10.2.3.4', CONFIG))
    assert len(calls) == 1


def test_missing_snmp_can_still_login_by_web_branding(monkeypatch):
    monkeypatch.setattr(auto, 'detect_vendor', AsyncMock(return_value=None))
    async def collect(address, config, transport):
        return {'vendor': 'MikroTik', 'web_url': 'https://10.2.3.4'}
    monkeypatch.setattr(online_device, 'collect_once', collect)
    result = asyncio.run(online_device.collect('10.2.3.4', CONFIG))
    assert result['detected_vendor'] == 'mikrotik' and result['snmp_version'] is None
    assert result['connection']['protocol'] == 'https'


def test_saved_login_automatically_detects_and_stale_session_never_probes(client, owner, monkeypatch):
    setup_login(client, owner, monkeypatch)
    calls = []
    async def collect(address, config):
        assert config['transport'] == 'auto'
        calls.append(address)
        return {'vendor': 'MikroTik'}
    monkeypatch.setattr(online_device, 'collect', collect)
    assert client.post(PATH + '/login', headers=owner, json=QUERY).status_code == 200
    assert client.post(PATH + '/login', headers=owner, json={**QUERY, 'session_id': 'stale'}).status_code == 409
    assert len(calls) == 1


def test_save_uses_resolved_connection_without_autodetection(client, owner, monkeypatch):
    setup_login(client, owner, monkeypatch)
    monkeypatch.setattr(auto, 'detect_vendor', AsyncMock(side_effect=AssertionError('Saving must never autodetect')))
    calls = []
    async def native(address, config, change):
        assert config['transport'] == 'routeros'
        assert config['port'] is None
        calls.append(change)
        return {'status': 'accepted'}
    monkeypatch.setattr(online_device, 'native_change', native)
    request = {**MANUAL, 'login': {**MANUAL['login'], 'transport': 'auto'}, 'change': CHANGE}
    assert client.put(PATH + '/settings', headers=owner, json=request).status_code == 409
    result = client.put(PATH + '/settings', headers=owner, json={**request, 'connection': {'transport': 'routeros'}})
    assert result.status_code == 200, result.text
    assert calls == [CHANGE]


def test_custom_web_port_is_not_reused_for_ssh_or_native_api():
    options = auto.candidates({**CONFIG, 'port': 8443}, 'generic')
    assert all(c['port'] == (8443 if c['transport'] == 'web' else None) for c in options)


def test_rejected_web_login_can_try_native_api_once(monkeypatch):
    monkeypatch.setattr(auto, 'detect_vendor', AsyncMock(return_value={'vendor': 'mikrotik', 'snmp_version': '2c'}))
    calls = []
    async def collect(address, config, transport):
        calls.append(config['transport'])
        if config['transport'] == 'web':
            raise PermissionError()
        return {'vendor': 'MikroTik'}
    monkeypatch.setattr(online_device, 'collect_once', collect)
    result = asyncio.run(online_device.collect('10.2.3.4', CONFIG))
    assert calls == ['web', 'routeros_tls']
    assert result['connection_attempts'][0]['status'] == 'Login rejected'
    assert result['connection']['transport'] == 'routeros_tls'


def test_snmp_known_unsupported_vendor_never_sends_device_password(monkeypatch):
    monkeypatch.setattr(auto, 'detect_vendor', AsyncMock(return_value={'vendor': 'mimosa', 'snmp_version': '2c'}))
    monkeypatch.setattr(online_device, 'collect_once', AsyncMock(side_effect=AssertionError('Unsupported vendor')))
    with pytest.raises(RuntimeError, match='another vendor'):
        asyncio.run(online_device.collect('10.2.3.4', CONFIG))
