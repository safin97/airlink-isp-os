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






def test_mikrotik_connections_are_sequential_stop_at_success_and_keep_resolved_transport(monkeypatch):
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
    assert calls == [('web', 'https'), ('web', 'http'), ('routeros_tls', 'both'), ('routeros', 'both')]
    assert result['connection']['transport'] == 'routeros'
    assert 'snmp_version' not in result
    assert len(result['connection_attempts']) == 4
    assert 'private' not in str(result)




def test_ssh_key_change_never_falls_back(monkeypatch):
    calls = []
    async def collect(*args):
        calls.append(True)
        raise ManagementError('SSH host key changed', 409)
    monkeypatch.setattr(online_device, 'collect_once', collect)
    with pytest.raises(ManagementError):
        asyncio.run(online_device.collect('10.2.3.4', CONFIG))
    assert len(calls) == 1


def test_missing_snmp_can_still_login_by_web_branding(monkeypatch):
    async def collect(address, config, transport):
        return {'vendor': 'MikroTik', 'web_url': 'https://10.2.3.4'}
    monkeypatch.setattr(online_device, 'collect_once', collect)
    result = asyncio.run(online_device.collect('10.2.3.4', CONFIG))
    assert result['detected_vendor'] == 'mikrotik' and 'snmp_version' not in result
    assert result['connection']['protocol'] == 'https'


@pytest.mark.parametrize('family', ['ubiquiti_m5', 'ubiquiti_ac'])
def test_airmax_automatic_login_preserves_m5_or_ac_family(monkeypatch, family):
    async def collect(address, config, transport):
        return {
            'vendor': 'Ubiquiti',
            'detected_vendor': family,
            'web_url': 'https://10.2.3.4',
        }
    monkeypatch.setattr(online_device, 'collect_once', collect)
    result = asyncio.run(online_device.collect('10.2.3.4', CONFIG))
    assert result['detected_vendor'] == family
    assert result['device_type'] == auto.VENDOR_LABELS[family]


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
    calls = []
    async def native(address, config, change):
        assert config['transport'] == 'routeros'
        assert config['verify_tls'] is True
        assert config['port'] is None
        calls.append(change)
        return {'status': 'accepted'}
    monkeypatch.setattr(online_device, 'native_change', native)
    request = {**MANUAL, 'login': {**MANUAL['login'], 'transport': 'auto'}, 'change': CHANGE}
    assert client.put(PATH + '/settings', headers=owner, json=request).status_code == 409
    result = client.put(PATH + '/settings', headers=owner, json={**request, 'connection': {'transport': 'routeros', 'verify_tls': False}})
    assert result.status_code == 200, result.text
    assert calls == [CHANGE]


def test_custom_web_port_is_not_reused_for_ssh_or_native_api():
    options = auto.candidates({**CONFIG, 'port': 8443}, 'generic')
    assert all(c['port'] == (8443 if c['transport'] == 'web' else None) for c in options)


def test_rejected_web_login_can_try_native_api_once(monkeypatch):
    calls = []
    async def collect(address, config, transport):
        calls.append(config['transport'])
        if config['transport'] == 'web':
            raise PermissionError()
        return {'vendor': 'MikroTik'}
    monkeypatch.setattr(online_device, 'collect_once', collect)
    result = asyncio.run(online_device.collect('10.2.3.4', CONFIG))
    assert calls == ['web', 'web', 'routeros_tls']
    assert result['connection_attempts'][0]['status'] == 'Login rejected'
    assert result['connection']['transport'] == 'routeros_tls'




def test_automatic_login_never_probes_snmp_and_background_skips_ssh(monkeypatch):
    monkeypatch.setattr(snmp_discovery, 'identify', AsyncMock(side_effect=AssertionError('No SNMP detection')))
    async def collect(address, config, transport):
        return {'vendor':'MikroTik', 'web_url':'https://10.2.3.4'}
    monkeypatch.setattr(online_device, 'collect_once', collect)
    assert asyncio.run(online_device.collect('10.2.3.4', CONFIG))['detected_vendor']=='mikrotik'
    assert all(c['transport']!='airos_ssh' for c in auto.candidates({**CONFIG,'background':True},'generic'))


def test_online_device_uses_own_panel_credentials_after_session_validation(client, owner, monkeypatch):
    setup_login(client, owner, monkeypatch)
    client.put('/api/integrations/sas4/device-access',headers=owner,
        json={'api_username':'panel-user','api_password':'panel-private'}).raise_for_status()
    calls=[]
    async def collect(address, config):
        assert config['api_username']=='panel-user' and config['api_password']=='panel-private'
        calls.append(address)
        return {'vendor':'MikroTik'}
    monkeypatch.setattr(online_device,'collect',collect)
    request={**QUERY,'use_online_login':True}
    result=client.post(PATH+'/login',headers=owner,json=request)
    assert result.status_code==200 and 'panel-private' not in result.text
    assert result.json()['credential_source']=='Online users device login'
    assert client.post(PATH+'/login',headers=owner,json={**request,'session_id':'stale'}).status_code==409
    assert len(calls)==1
