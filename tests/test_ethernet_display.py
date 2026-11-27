from datetime import timedelta
import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect

from airlink import device_telemetry
from airlink.db import SessionLocal, engine
from airlink.models import Device, Metric, now
from test_api import tower, user


def create(client, owner, tid, vendor='mikrotik'):
    return client.post('/api/devices', headers=owner, json={
        'name': 'Radio', 'ip_address': '192.0.2.10', 'tower_id': tid,
        'vendor': vendor}).json()['id']


def poll(did, values, stamp):
    with SessionLocal() as db:
        device = db.get(Device, did)
        device.last_poll = stamp
        device.status = 'online' if values.get('snmp_up') or values.get('api_up') else 'offline'
        device_telemetry.remember(db, device, values, stamp)
        db.add(Metric(device_id=did, values=values, collected_at=stamp))
        db.commit()


@pytest.mark.parametrize('vendor', ['mikrotik', 'mimosa', 'ruijie', 'ubiquiti'])
def test_automatic_uses_available_speed_then_retains_last_port(client, owner, vendor):
    did = create(client, owner, tower(client, owner), vendor)
    stamp = now() - timedelta(seconds=30)
    def sample(offset, ports):
        values = {'snmp_up': ports is not None, 'interfaces': ports or {}}
        poll(did, values, stamp + timedelta(seconds=offset))
        return client.get('/api/devices', headers=owner).json()[0]
    def port(name, speed, **extra):
        return {'name': name, 'type': 6, 'status': 1, 'speed_mbps': speed, **extra}
    first = sample(0, {'1': port('ether1', 1000, admin_status=2),
                       '2': port('eth0', 1000), '3': port('wlan0', 866, type=71),
                       '4': port('bridge', 10000, type=209)})
    assert first['ethernet_auto']['name'] == 'eth0'
    assert first['ethernet_auto']['speed_mbps'] == 1000
    assert first['ethernet_auto']['stale'] is False
    second = sample(1, {'2': port('eth0', 1000, status=2), '3': port('ether2', 100)})
    assert second['ethernet_auto']['name'] == 'ether2'
    assert second['ethernet_auto']['speed_mbps'] == 100
    # Stable choice while it remains available, irrespective of walk order.
    stable = sample(2, {'4': port('aaa', 10000), '3': port('ether2', 100)})
    assert stable['ethernet_auto']['name'] == 'ether2'
    preferred = sample(3, {'3': port('ether2', 100), '1': port('ether1', 10)})
    assert preferred['ethernet_auto']['name'] == 'ether1'
    fallback = sample(4, {'1': port('ether1', 0), '2': port('eth0', 2500),
                          '5': port('bad', True)})
    assert fallback['ethernet_auto']['name'] == 'eth0'
    assert fallback['ethernet_auto']['speed_mbps'] == 2500
    for offset, ports in [(5, {}), (6, None)]:
        stale = sample(offset, ports)
        assert stale['ethernet_auto'] == {**fallback['ethernet_auto'], 'stale': True}
        assert '_ethernet_auto' not in stale['telemetry']
    # An explicit choice remains saved even though Automatic has found another port.
    path = '/api/devices/' + did + '/ethernet-display'
    client.put(path, headers=owner, json={'port': 'ether2'}).raise_for_status()
    selected = client.get('/api/devices', headers=owner).json()[0]
    assert selected['ethernet_speed_port'] == 'ether2'
    assert selected['telemetry']['ethernet_selected']['name'] == 'ether2'
    client.put(path, headers=owner, json={'port': None}).raise_for_status()
    reset = client.get('/api/devices', headers=owner).json()[0]
    assert reset['ethernet_speed_port'] is None
    assert reset['ethernet_auto']['name'] == 'eth0'


@pytest.mark.parametrize('vendor', ['mikrotik', 'mimosa', 'ruijie', 'ubiquiti'])
def test_selected_port_history_survives_other_ports_outage_and_edit(client, owner, vendor):
    tid = tower(client, owner)
    did = create(client, owner, tid, vendor)
    path = '/api/devices/' + did
    stamp = now() - timedelta(seconds=30)
    p1 = {'name': 'ether1', 'type': 6, 'status': 1, 'speed_mbps': 1000}
    p2 = {'name': 'ether2', 'type': 6, 'status': 1, 'speed_mbps': 100}
    poll(did, {'snmp_up': True, 'interfaces': {'1': p1, '2': p2}}, stamp)
    before = client.get('/api/devices', headers=owner).json()[0]
    assert client.put(path+'/ethernet-display', headers=owner, json={'port': 'ether2'}).status_code == 200
    row = client.get('/api/devices', headers=owner).json()[0]
    assert row['last_poll'] == before['last_poll'] and row['status'] == before['status']
    assert row['ethernet_speed_port'] == 'ether2'
    assert row['telemetry']['ethernet_selected'] == {'name': 'ether2', 'speed_mbps': 100}
    original_time = row['telemetry_field_times']['ethernet_selected']
    poll(did, {'snmp_up': True, 'interfaces': {'1': {**p1, 'speed_mbps': 2500}}}, stamp + timedelta(seconds=1))
    row = client.get('/api/devices', headers=owner).json()[0]
    assert row['telemetry']['ethernet_selected']['speed_mbps'] == 100
    assert row['telemetry_field_times']['ethernet_selected'] == original_time
    assert 'ethernet_selected' in row['telemetry_stale_fields']
    # Only the selected port responds; automatic ether1 retention must not hide it.
    poll(did, {'snmp_up': True, 'interfaces': {'2': {**p2, 'speed_mbps': 1000}}}, stamp + timedelta(seconds=2))
    row = client.get('/api/devices', headers=owner).json()[0]
    assert row['telemetry']['ethernet_selected']['speed_mbps'] == 1000
    assert 'ethernet_selected' not in row['telemetry_stale_fields']
    new_time = row['telemetry_field_times']['ethernet_selected']
    poll(did, {'snmp_up': False, 'interfaces': {}}, stamp + timedelta(seconds=3))
    row = client.get('/api/devices', headers=owner).json()[0]
    assert row['telemetry']['ethernet_selected']['speed_mbps'] == 1000
    assert row['telemetry_field_times']['ethernet_selected'] == new_time
    assert 'ethernet_selected' in row['telemetry_stale_fields']
    assert '_ethernet_port_history' not in row['telemetry']
    choices = client.get(path+'/ethernet-ports', headers=owner).json()
    assert choices['speed_port'] == 'ether2' and choices['speed_port_choices'] == ['ether1', 'ether2']
    edited = client.put(path, headers=owner, json={
        'name': 'Renamed', 'ip_address': '192.0.2.10', 'tower_id': tid, 'vendor': vendor})
    assert edited.status_code == 200 and edited.json()['ethernet_speed_port'] == 'ether2'
    assert client.put(path+'/ethernet-display', headers=owner, json={'port': None}).status_code == 200
    row = client.get('/api/devices', headers=owner).json()[0]
    assert row['ethernet_speed_port'] is None and 'ethernet_selected' not in row['telemetry']


def test_api_only_choices_and_down_port_never_borrow_another_speed(client, owner):
    did = create(client, owner, tower(client, owner))
    path = '/api/devices/' + did
    poll(did, {'api_up': True, 'ethernet_links': [{'name': 'sfp1', 'speed_mbps': 10000}],
               'interfaces': {'2': {'name': 'ether2', 'type': 6, 'status': 2},
                              '3': {'name': 'bridge', 'type': 209}}}, now())
    result = client.get(path+'/ethernet-ports', headers=owner).json()
    assert result['supported'] is False  # No SNMP profile; API link choices still work.
    assert result['speed_port_choices'] == ['ether2', 'sfp1']
    assert client.put(path+'/ethernet-display', headers=owner, json={'port': 'sfp1'}).status_code == 200
    assert client.get('/api/devices', headers=owner).json()[0]['telemetry']['ethernet_selected']['speed_mbps'] == 10000
    assert client.put(path+'/ethernet-display', headers=owner, json={'port': 'ether2'}).status_code == 200
    assert 'ethernet_selected' not in client.get('/api/devices', headers=owner).json()[0]['telemetry']
    for invalid in ['bridge', 'unknown', '', '\n', 'x'*129]:
        assert client.put(path+'/ethernet-display', headers=owner, json={'port': invalid}).status_code == 422


def test_selection_requires_tower_edit_access_and_device_scope(client, owner):
    uid, manager = user(client, owner, 'manager')
    tid = tower(client, owner, manager=uid)
    did = create(client, owner, tid)
    path = '/api/devices/' + did
    client.put('/api/users/'+uid+'/sections', headers=owner,
               json={'sections': ['towers'], 'editable_sections': []}).raise_for_status()
    assert client.get(path+'/ethernet-ports', headers=manager).json()['can_select_speed_port'] is False
    assert client.put(path+'/ethernet-display', headers=manager, json={'port': None}).status_code == 403
    client.put('/api/users/'+uid+'/sections', headers=owner,
               json={'sections': ['towers'], 'editable_sections': ['towers']}).raise_for_status()
    assert client.get(path+'/ethernet-ports', headers=manager).json()['can_select_speed_port'] is True
    assert client.put(path+'/ethernet-display', headers=manager, json={'port': None}).status_code == 200
    with SessionLocal() as db:
        db.get(Device, did).tower_id = tower(client, owner, 'Other')
        db.commit()
    assert client.put(path+'/ethernet-display', headers=manager, json={'port': None}).status_code == 404
    assert client.put(path+'/ethernet-display', json={'port': None}).status_code == 401


def test_selection_migration_preserves_existing_devices(client, owner):
    did = create(client, owner, tower(client, owner))
    path = Path(__file__).resolve().parents[1] / 'database/versions/e97ab6038214_device_ethernet_speed_port.py'
    spec = importlib.util.spec_from_file_location('ethernet_selection_migration', path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with engine.begin() as conn:
        with Operations.context(MigrationContext.configure(conn)):
            migration.downgrade()
            assert 'ethernet_speed_port' not in {c['name'] for c in inspect(conn).get_columns('devices')}
            migration.upgrade()
    with SessionLocal() as db:
        assert db.get(Device, did).ethernet_speed_port is None
        assert db.get(Device, did).name == 'Radio'
