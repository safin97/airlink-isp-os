import ipaddress
import subprocess
import pytest
from airlink import discovery
from test_api import user


def test_discovery_scope_results_and_existing_devices(client, owner, monkeypatch):
    tower = client.post('/api/towers', headers=owner, json={
        'name': 'North', 'management_ip': '192.0.2.9'}).json()
    client.post('/api/devices', headers=owner, json={
        'tower_id': tower['id'], 'name': 'Existing', 'ip_address': '192.0.2.10'})
    seen = []
    def scan(network):
        seen.append(str(network))
        return ['192.0.2.9', '192.0.2.10']
    monkeypatch.setattr(discovery, 'scan', scan)
    url = f"/api/towers/{tower['id']}/discover"
    result = client.post(url, headers=owner, json={'prefix': 28})
    assert result.status_code == 200, result.text
    assert seen == ['192.0.2.0/28']
    assert result.json()['scanned'] == 14
    assert result.json()['hosts'] == [
        {'ip_address': '192.0.2.9', 'already_added': False},
        {'ip_address': '192.0.2.10', 'already_added': True}]
    assert len(client.get('/api/devices', headers=owner).json()) == 1
    assert client.post(url, headers=owner, json={'prefix': 16}).status_code == 422
    assert client.post(url, json={'prefix': 24}).status_code in (401, 403)
    _, viewer = user(client, owner, 'viewer')
    assert client.post(url, headers=viewer, json={'prefix': 24}).status_code == 403
    _, manager = user(client, owner, 'manager')
    assert client.post(url, headers=manager, json={'prefix': 24}).status_code == 404
    assert seen == ['192.0.2.0/28']


def test_discovery_missing_ip_and_ping_error(client, owner, monkeypatch):
    tower = client.post('/api/towers', headers=owner, json={'name': 'Empty'}).json()
    url = f"/api/towers/{tower['id']}/discover"
    assert client.post(url, headers=owner, json={}).status_code == 422
    client.put(f"/api/towers/{tower['id']}", headers=owner,
               json={'name': 'Empty', 'management_ip': '192.0.2.1'})
    def fail(network):
        raise RuntimeError('Ping not installed')
    monkeypatch.setattr(discovery, 'scan', fail)
    assert client.post(url, headers=owner, json={}).status_code == 503
    monkeypatch.setattr(discovery, 'scan', lambda network: [])
    result = client.post(url, headers=owner, json={})
    assert result.status_code == 200, result.text
    assert result.json()['hosts'] == []


def test_bounded_ping_scan(monkeypatch):
    monkeypatch.setattr(discovery.shutil, 'which', lambda name: '/sbin/ping')
    def ping(executable, address):
        if address == '192.0.2.2':
            raise subprocess.TimeoutExpired('ping', 3)
        return True
    monkeypatch.setattr(discovery, 'ping_host', ping)
    assert discovery.scan(ipaddress.ip_network('192.0.2.0/30')) == ['192.0.2.1']
    with pytest.raises(ValueError):
        discovery.management_network('::1', 24)
    assert str(discovery.management_network('192.0.2.9', 32)) == '192.0.2.9/32'
