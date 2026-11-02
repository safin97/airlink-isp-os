from datetime import timedelta
from types import SimpleNamespace
import pytest

from airlink.client_telemetry import attach_telemetry
from airlink.db import SessionLocal
from airlink.models import Device, Metric, now
from test_api import user, tower, device


@pytest.mark.parametrize('assignment', ['tower', 'place'])
def test_online_customer_telemetry_is_scoped_and_fresh(client, owner, assignment):
    manager_id, _ = user(client, owner, 'manager')
    own = tower(client, owner, 'Own', manager=manager_id)
    if assignment == 'place':
        from test_places import place
        pid = place(client, owner)
        assert client.put('/api/towers/' + own, headers=owner,
                          json={'name': 'Own', 'place_id': pid}).status_code == 200
        assert client.put('/api/users/' + manager_id, headers=owner,
                          json={'username': 'manager', 'place_ids': [pid]}).status_code == 200
    other = tower(client, owner, 'Other')
    did = device(client, owner, own)
    other_id = device(client, owner, other, '192.0.2.2')
    profile = client.post('/api/snmp-profiles', headers=owner, json={
        'name': 'CPE', 'version': '2c', 'community': 'read-only-private'}).json()['id']
    manager = SimpleNamespace(id=manager_id, role='manager')
    def result():
        return {'clients': [{'ip_address': '192.0.2.1'}, {'ip_address': '192.0.2.2'}, {'ip_address': '192.0.2.3'}]}
    with SessionLocal() as db:
        for id in (did, other_id):
            d = db.get(Device, id)
            d.snmp_profile_id = profile
            d.last_poll = now()
            db.add(Metric(device_id=id, values={'snmp_up': True,
                'interfaces': {
                    '1': {'name': 'eth0', 'type': 6, 'status': 1, 'speed_mbps': 100},
                    '2': {'name': 'wlan0', 'type': 71, 'status': 1, 'speed_mbps': 300},
                    '3': {'name': 'eth1', 'type': 6, 'status': 2, 'speed_mbps': 1000}},
                'wireless': {'signal_dbm': {'1': -62}}}))
        db.commit()
        rows = attach_telemetry(db, manager, result())['clients']
        assert rows[0]['ethernet_links'] == [{'name': 'eth0', 'speed_mbps': 100}]
        assert rows[0]['signal_dbm'] == -62
        for row in rows[1:]:
            assert row['ethernet_links'] == [] and row['signal_dbm'] is None
            assert row['telemetry_status'] == 'not_monitored'
        # Latest failure wins over an older successful reading.
        latest = Metric(device_id=did, values={'snmp_up': False})
        db.add(latest); db.commit()
        assert attach_telemetry(db, manager, result())['clients'][0]['telemetry_status'] == 'failed'
        latest.collected_at = now() - timedelta(minutes=10)
        for metric in db.query(Metric).filter(Metric.device_id == did):
            metric.collected_at = now() - timedelta(minutes=10)
        db.commit()
        row = attach_telemetry(db, manager, result())['clients'][0]
        assert row['telemetry_status'] == 'stale' and row['signal_dbm'] is None
        d = db.get(Device, did); d.last_poll = None; db.commit()
        assert attach_telemetry(db, manager, result())['clients'][0]['telemetry_status'] == 'pending'


def test_online_telemetry_never_uses_aggregate_ap_signal(client, owner):
    tid = tower(client, owner)
    did = device(client, owner, tid)
    profile = client.post('/api/snmp-profiles', headers=owner, json={
        'name': 'CPE', 'version': '2c', 'community': 'private'}).json()['id']
    with SessionLocal() as db:
        d = db.get(Device, did); d.snmp_profile_id = profile; d.last_poll = now()
        db.add(Metric(device_id=did, values={'snmp_up': True, 'weakest_signal_dbm': -80,
            'wireless': {'signal_dbm': {'1': -55, '2': -80}}}))
        db.commit()
        rows = attach_telemetry(db, SimpleNamespace(role='owner'), {'clients': [{'ip_address':'192.0.2.1'}]})['clients']
        assert rows[0]['signal_dbm'] is None
        assert rows[0]['ethernet_links'] == []


def test_online_telemetry_uses_fresh_api_without_snmp_profile(client, owner):
    tid = tower(client, owner)
    did = device(client, owner, tid)
    with SessionLocal() as db:
        d = db.get(Device, did)
        d.last_poll = now()
        db.add(Metric(device_id=did, values={'api_up': True, 'telemetry_source':'airOS API',
            'ethernet_links':[{'name':'eth0','speed_mbps':1000}], 'signal_dbm':-59}))
        db.commit()
        row = attach_telemetry(db, SimpleNamespace(role='owner'), {'clients':[{'ip_address':'192.0.2.1'}]})['clients'][0]
        assert row['signal_dbm'] == -59 and row['ethernet_links'][0]['speed_mbps'] == 1000
        assert row['telemetry_source'] == 'airOS API' and row['device_reachable'] is True
