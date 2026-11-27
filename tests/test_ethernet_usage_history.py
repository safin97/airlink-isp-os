from datetime import timedelta

import pytest
from airlink import ethernet_history
from airlink.db import SessionLocal
from airlink.models import Device, DeviceTelemetrySnapshot, Metric, now
from test_api import tower, user
from test_ethernet_display import create, poll


def test_existing_active_link_history_counts_but_other_address_does_not():
    stamp = now()
    previous = stamp - timedelta(minutes=1)
    fields = {'ethernet_links': {'value': [{'name': 'ether1', 'speed_mbps': 1000}],
                                'address': '192.0.2.1', 'observed_at': previous.isoformat()}}
    values = {'snmp_up': True, 'interfaces': {
        '1': {'name': 'ether1', 'type': 6, 'status': 2},
        '2': {'name': 'ether2', 'type': 6, 'status': 2},
    }}
    history = ethernet_history.remember(fields, values, stamp, '192.0.2.1')
    assert ethernet_history.status(history['ports']['ether1']) == 'down'
    assert ethernet_history.status(history['ports']['ether2']) == 'unused'
    changed = ethernet_history.remember(fields, values, stamp, '192.0.2.2')
    assert all(ethernet_history.status(row) == 'unused' for row in changed['ports'].values())


@pytest.mark.parametrize('source', ['snmp', 'api'])
def test_only_used_ports_go_down_and_resolution_rearms_after_reuse(client, owner, source):
    mid, manager = user(client, owner, 'manager')
    _, outsider = user(client, owner, 'manager', 'outside')
    tid = tower(client, owner, manager=mid)
    did = create(client, owner, tid)
    if source == 'snmp':
        profile = client.post('/api/snmp-profiles', headers=owner, json={
            'name': 'Ports', 'version': '2c', 'community': 'test'}).json()['id']
        with SessionLocal() as db:
            db.get(Device, did).snmp_profile_id = profile
            db.commit()
    client.put('/api/users/' + mid + '/sections', headers=owner,
               json={'sections': ['towers'], 'editable_sections': []}).raise_for_status()
    stamp = now() - timedelta(seconds=30)
    path = '/api/devices/' + did + '/ethernet-ports'

    def sample(offset, first, second):
        ports = [{'name': 'ether1', 'type': 6, 'status': first},
                 {'name': 'ether2', 'type': 6, 'status': second},
                 {'name': 'ether3', 'type': 6, 'status': 2, 'admin_status': 2}]
        values = ({'snmp_up': True, 'interfaces': {str(i+1): p for i, p in enumerate(ports)}}
                  if source == 'snmp' else {'api_up': True, 'ethernet_port_states': ports})
        poll(did, values, stamp + timedelta(seconds=offset))
        return client.get(path, headers=owner).json()['ports']

    def counts():
        telemetry = client.get('/api/devices', headers=owner).json()[0]['telemetry']
        assert '_ethernet_usage_history' not in telemetry
        return telemetry['ethernet_port_counts']

    first = sample(0, 1, 2)
    assert [p['usage_status'] for p in first] == ['running', 'unused', 'unused']
    assert counts() == {'online': 1, 'offline': 0, 'unused': 2, 'resolved': 0, 'unknown': 0}
    moved = sample(1, 2, 1)
    assert [p['usage_status'] for p in moved] == ['down', 'running', 'unused']
    assert counts()['offline'] == 1
    body = {'port': 'ether1', 'down_since': moved[0]['down_since']}
    assert moved[0]['can_resolve'] and not moved[2]['can_resolve']
    assert client.post(path + '/resolve', json=body).status_code == 401
    assert client.post(path + '/resolve', headers=manager, json=body).status_code == 403
    assert client.post(path + '/resolve', headers=outsider, json=body).status_code == 404
    assert client.post(path + '/resolve', headers=owner, json={**body, 'port': 'ether3'}).status_code == 409
    assert client.post(path + '/resolve', headers=owner, json=body).status_code == 200
    assert counts()['offline'] == 0 and counts()['resolved'] == 1
    resolved = sample(2, 2, 1)
    assert resolved[0]['usage_status'] == 'resolved' and not resolved[0]['can_resolve']
    assert counts()['offline'] == 0
    # Resolution survives raw metric retention and a new DB session.
    with SessionLocal() as db:
        db.query(Metric).filter(Metric.device_id == did).delete()
        assert db.get(DeviceTelemetrySnapshot, did).fields['_ethernet_usage_history']['ports']['ether1']['resolved_at']
        db.commit()
    assert counts()['offline'] == 0 and counts()['resolved'] == 1
    sample(3, 1, 1)
    again = sample(4, 2, 1)
    assert again[0]['usage_status'] == 'down' and again[0]['can_resolve']
    assert again[0]['down_since'] != body['down_since']
    assert counts()['offline'] == 1
    assert client.post(path + '/resolve', headers=owner, json=body).status_code == 409
    # A different device address cannot inherit usage or acknowledgement.
    with SessionLocal() as db:
        db.get(Device, did).ip_address = '192.0.2.99'
        db.commit()
    changed = sample(5, 2, 2)
    assert all(p['usage_status'] == 'unused' for p in changed)
    assert counts()['offline'] == 0


def test_partial_port_walk_does_not_present_retained_usage_as_current(client, owner):
    tid = tower(client, owner)
    did = create(client, owner, tid)
    profile = client.post('/api/snmp-profiles', headers=owner, json={
        'name': 'Partial ports', 'version': '2c', 'community': 'test'}).json()['id']
    with SessionLocal() as db:
        db.get(Device, did).snmp_profile_id = profile
        db.commit()
    stamp = now() - timedelta(seconds=30)
    path = '/api/devices/' + did + '/ethernet-ports'
    values = {'snmp_up': True, 'ethernet_ports_complete': True, 'interfaces': {
        '1': {'name': 'ether1', 'type': 6, 'status': 1}}}
    poll(did, values, stamp)
    values['interfaces']['1']['status'] = 2
    poll(did, values, stamp + timedelta(seconds=1))
    assert client.get(path, headers=owner).json()['ports'][0]['usage_status'] == 'down'
    values['ethernet_ports_complete'] = False
    values['interfaces']['1']['status'] = 1
    poll(did, values, stamp + timedelta(seconds=2))
    port = client.get(path, headers=owner).json()['ports'][0]
    assert port['usage_status'] == 'unknown'
    assert port['can_resolve'] is True  # The recorded outage can still be acknowledged.
    with SessionLocal() as db:
        db.get(Device, did).ip_address = '192.0.2.99'
        db.commit()
    port = client.get(path, headers=owner).json()['ports'][0]
    assert port['usage_status'] == 'unknown'
    assert port['can_resolve'] is False
