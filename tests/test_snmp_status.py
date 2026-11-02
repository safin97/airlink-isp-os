from datetime import timedelta

import pytest

from airlink.db import SessionLocal
from airlink.models import Device, Metric, now
from test_api import tower, device


@pytest.mark.parametrize('configured,enabled,last_poll,sample,result,expected', [
    (False, True, True, 'fresh', True, 'not_configured'),
    (True, False, True, 'fresh', True, 'disabled'),
    (True, True, False, 'fresh', True, 'pending'),
    (True, True, True, None, None, 'pending'),
    (True, True, True, 'fresh', None, 'pending'),
    (True, True, True, 'fresh', True, 'connected'),
    (True, True, True, 'fresh', False, 'failed'),
    (True, True, True, 'stale', True, 'stale'),
    (True, True, True, 'stale', False, 'stale'),
])
def test_snmp_status_is_separate_from_ping(client, owner, configured, enabled, last_poll, sample, result, expected):
    tid = tower(client, owner)
    did = device(client, owner, tid)
    profile = client.post('/api/snmp-profiles', headers=owner, json={
        'name': 'Read only', 'version': '2c', 'community': 'private-community'}).json()['id']
    with SessionLocal() as db:
        obj = db.get(Device, did)
        obj.snmp_profile_id = profile if configured else None
        obj.enabled = enabled
        obj.status = 'online'
        obj.last_poll = now() if last_poll else None
        if sample:
            values = {'icmp_up': True}
            if result is not None:
                values['snmp_up'] = result
            db.add(Metric(device_id=did, collected_at=now() - timedelta(minutes=10 if sample == 'stale' else 0), values=values))
        db.commit()
    response = client.get('/api/devices', headers=owner)
    assert response.status_code == 200, response.text
    assert response.json()[0]['snmp_status'] == expected
    assert 'private-community' not in response.text
    if expected == 'failed':
        assert response.json()[0]['status'] == 'online'


def test_latest_poll_and_profile_change(client, owner):
    tid = tower(client, owner)
    did = device(client, owner, tid)
    profile = client.post('/api/snmp-profiles', headers=owner, json={
        'name': 'Read only', 'version': '2c', 'community': 'private-community'}).json()['id']
    with SessionLocal() as db:
        obj = db.get(Device, did)
        obj.snmp_profile_id = profile
        obj.last_poll = now()
        db.add_all([
            Metric(device_id=did, collected_at=now()-timedelta(seconds=10), values={'snmp_up': True}),
            Metric(device_id=did, collected_at=now(), values={'snmp_up': False}),
        ])
        db.commit()
    assert client.get('/api/devices', headers=owner).json()[0]['snmp_status'] == 'failed'
    response = client.put('/api/devices/' + did, headers=owner, json={
        'name': 'Router', 'ip_address': '192.0.2.20', 'tower_id': tid, 'snmp_profile_id': profile})
    assert response.status_code == 200, response.text
    assert client.get('/api/devices', headers=owner).json()[0]['snmp_status'] == 'pending'
