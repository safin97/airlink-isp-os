from datetime import timedelta

from airlink import device_api, device_telemetry
from airlink.db import SessionLocal
from airlink.models import Device, DeviceTelemetrySnapshot, Metric, now
from test_api import device, tower


def test_port_counts_exclude_virtual_interfaces_and_retain_last_reading(client, owner):
    did = device(client, owner, tower(client, owner))
    stamp = now()
    ports = {
        '1': {'type': 6, 'status': 1},
        '2': {'type': 6, 'status': 2},
        '3': {'type': 6, 'status': 1, 'admin_status': 2},
        '4': {'type': 6},
        '5': {'type': 6, 'status': 3},
        '6': {'type': 6, 'status': 7},
        '7': {'type': 135, 'status': 1},
        '8': {'type': 209, 'status': 2},
        '9': {'type': 71, 'status': 1},
    }
    expected = {'online': 1, 'offline': 3, 'unknown': 2}
    values = {'snmp_up': True, 'interfaces': ports, 'ethernet_ports_complete': True}
    assert device_telemetry.readings(values, 'generic')['ethernet_port_counts'] == expected
    expected = {'online': 1, 'offline': 0, 'unknown': 2, 'unused': 3, 'resolved': 0}
    with SessionLocal() as db:
        d = db.get(Device, did)
        d.last_poll = stamp
        device_telemetry.remember(db, d, values, stamp)
        db.commit()
        snapshot = db.get(DeviceTelemetrySnapshot, did)
        for failed in (
                {'snmp_up': True, 'interfaces': {'1': ports['1']}, 'ethernet_ports_complete': False},
                {'icmp_up': True, 'snmp_up': False, 'interfaces': ports},
                {'icmp_up': False, 'snmp_up': False},
                {'snmp_up': True, 'interfaces': {}}):
            later = stamp + timedelta(minutes=1)
            d.last_poll = later
            device_telemetry.remember(db, d, failed, later)
            metric = Metric(device_id=did, collected_at=later, values=failed)
            display = device_telemetry.display(d, metric, snapshot, True, 'generic')
            assert display['telemetry']['ethernet_port_counts'] == expected
            assert 'ethernet_port_counts' in display['telemetry_stale_fields']
            assert display['telemetry_field_times']['ethernet_port_counts'] == stamp.isoformat()
        recovered = {'snmp_up': True, 'interfaces': {'1': {'type': 6, 'status': 2}}}
        device_telemetry.remember(db, d, recovered, later)
        metric = Metric(device_id=did, collected_at=later, values=recovered)
        display = device_telemetry.display(d, metric, snapshot, True, 'generic')
        assert display['telemetry']['ethernet_port_counts'] == {
            'online': 0, 'offline': 1, 'unknown': 5, 'unused': 0, 'resolved': 0}
        assert 'ethernet_port_counts' not in display['telemetry_stale_fields']


def test_airos_counts_disconnected_ethernet_without_counting_radio_or_bridge():
    values = device_api.airos_values({'wireless': {}, 'interfaces': [
        {'ifname': 'eth0', 'status': {'plugged': '1', 'speed': 1000}},
        {'ifname': 'eth1', 'status': {'plugged': '0'}},
        {'ifname': 'eth2', 'status': {}},
        {'ifname': 'ath0', 'status': {'plugged': 1}},
        {'ifname': 'br0', 'status': {'plugged': 1}},
    ]}, inventory=True)
    assert values['ethernet_port_counts'] == {'online': 1, 'offline': 1, 'unknown': 1}
