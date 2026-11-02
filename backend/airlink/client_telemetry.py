"""Enrich SAS4 sessions with fresh SNMP readings from the matching customer IP."""
import math
from sqlalchemy import select
from .models import Device, Metric, Tower, now
from .security import aware


def number(value, low, high):
    return (not isinstance(value, bool) and isinstance(value, (int, float))
            and math.isfinite(value) and low <= value <= high)


def attach_telemetry(db, user, result):
    rows = result.get('clients', [])
    addresses = {row['ip_address'] for row in rows if isinstance(row.get('ip_address'), str)}
    latest = (select(Metric.id).where(Metric.device_id == Device.id)
              .order_by(Metric.collected_at.desc(), Metric.id.desc()).limit(1).correlate(Device).scalar_subquery())
    query = (select(Device, Metric).outerjoin(Metric, Metric.id == latest)
             .where(Device.ip_address.in_(addresses)))
    if user.role != 'owner':
        query = query.where(Device.tower_id.in_(select(Tower.id).where(Tower.manager_id == user.id)))
    matches = {device.ip_address: (device, metric) for device, metric in db.execute(query)} if addresses else {}
    for row in rows:
        row.update(ethernet_links=[], signal_dbm=None, telemetry_status='not_monitored')
        address = row.get('ip_address')
        match = matches.get(address) if isinstance(address, str) else None
        if not match:
            continue
        device, metric = match
        if not device.enabled or not device.snmp_profile_id:
            continue
        row['telemetry_status'] = 'pending'
        if not device.last_poll or not metric:
            continue
        if (now() - aware(metric.collected_at)).total_seconds() > device.poll_interval * 3 + 30:
            row['telemetry_status'] = 'stale'
            continue
        if metric.values.get('snmp_up') is not True:
            row['telemetry_status'] = 'failed'
            continue
        row['telemetry_status'] = 'available'
        # IANA ifType ethernetCsmacd(6). Do not mistake Wi-Fi or bridge bandwidth
        # for an Ethernet link, and do not report a down port's nominal speed.
        for index, interface in metric.values.get('interfaces', {}).items():
            speed = interface.get('speed_mbps')
            if interface.get('type') == 6 and interface.get('status') == 1 and number(speed, 0.001, 1e9):
                row['ethernet_links'].append({'name': interface.get('name', index), 'speed_mbps': speed})
        signals = metric.values.get('wireless', {}).get('signal_dbm', {})
        # Multiple station/radio readings cannot identify this customer's link.
        # Never substitute an access point's weakest/aggregate signal.
        if len(signals) == 1:
            signal = next(iter(signals.values()))
            if number(signal, -150, -0.001):
                row['signal_dbm'] = signal
    return result
