"""Enrich SAS4 sessions with fresh SNMP readings from the matching customer IP."""
import math
from sqlalchemy import select
from .models import Device, Metric, now
from .manager_places import managed_towers
from .security import aware
from .vendor_identity import VENDOR_LABELS


def number(value, low, high):
    return (not isinstance(value, bool) and isinstance(value, (int, float))
            and math.isfinite(value) and low <= value <= high)


def snmp_readings(values):
    links = []
    for index, port in values.get('interfaces', {}).items():
        speed = port.get('speed_mbps')
        if port.get('type') == 6 and port.get('status') == 1 and number(speed, .001, 1e9):
            links.append({'name': str(port.get('name', index))[:120], 'speed_mbps': speed})
    ether1 = [port for port in links if port['name'].casefold() == 'ether1']
    wireless = values.get('wireless', {})
    signals = wireless.get('station_signal_dbm') or wireless.get('signal_dbm', {})
    strength = next(iter(signals.values())) if len(signals) == 1 else None
    ssids = {value for value in wireless.get('ssid', {}).values() if isinstance(value, str) and value}
    return {'ethernet_links': ether1 or links,
            'signal_dbm': strength if number(strength, -150, -.001) else None,
            'ssid': next(iter(ssids)) if len(ssids) == 1 else None}


def attach_telemetry(db, user, result):
    rows = result.get('clients', [])
    addresses = {row['ip_address'] for row in rows if isinstance(row.get('ip_address'), str)}
    latest = (select(Metric.id).where(Metric.device_id == Device.id)
              .order_by(Metric.collected_at.desc(), Metric.id.desc()).limit(1).correlate(Device).scalar_subquery())
    query = (select(Device, Metric).outerjoin(Metric, Metric.id == latest)
             .where(Device.ip_address.in_(addresses)))
    if user.role != 'owner':
        query = query.where(Device.tower_id.in_(managed_towers(user.id)))
    matches = {device.ip_address: (device, metric) for device, metric in db.execute(query)} if addresses else {}
    for row in rows:
        row.update(ethernet_links=[], signal_dbm=None, ssid=None, telemetry_status='not_monitored')
        address = row.get('ip_address')
        match = matches.get(address) if isinstance(address, str) else None
        if not match:
            continue
        device, metric = match
        if not device.enabled:
            continue
        row['telemetry_status'] = 'pending'
        if not device.last_poll or not metric:
            continue
        if (now() - aware(metric.collected_at)).total_seconds() > device.poll_interval * 3 + 30:
            row['telemetry_status'] = 'stale'
            continue
        snmp_ok = metric.values.get('snmp_up') is True
        if not snmp_ok:
            row['telemetry_status'] = 'failed'
            continue
        vendor = metric.values.get('detected_vendor') or device.vendor
        if vendor in VENDOR_LABELS and vendor != 'generic':
            row.update(detected_vendor=vendor, vendor_label=VENDOR_LABELS[vendor], vendor_detection_source='Inventory')
        row['telemetry_status'] = 'available'
        row['device_reachable'] = True
        row['telemetry_source'] = 'SNMP'
        row.update(snmp_readings(metric.values))
    return result
