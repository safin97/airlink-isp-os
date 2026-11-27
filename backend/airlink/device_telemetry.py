"""Last known display readings. Never substitute these for live monitoring samples."""
import math
from .models import DeviceTelemetrySnapshot
from .security import aware
from .wireless_clients import HISTORY_KEY, remember_clients

FIELDS = ('cpu_percent', 'memory_percent', 'uptime_seconds', 'ethernet_links',
          'signal_dbm', 'weakest_signal_dbm', 'wireless_clients', 'radio_frequencies_mhz',
          'wireless_ssids', 'firmware_version', 'device_model', 'telemetry_source')


def readings(values, vendor, previous=None):
    # Failed probes must not turn empty/default fields into fresh observations.
    states = [values[key] for key in ('icmp_up', 'snmp_up', 'api_up') if key in values]
    if states and not any(states) and values.get('api_status') != 'connected':
        return {}
    result = {key: values[key] for key in FIELDS if key in values and values[key] is not None}
    if 'interfaces' in values and 'ethernet_links' not in result:
        result['ethernet_links'] = [{'name': port.get('name', index), 'speed_mbps': port['speed_mbps']}
            for index, port in values['interfaces'].items()
            if port.get('type') == 6 and port.get('status') == 1 and port.get('speed_mbps', 0) > 0]
    if vendor == 'mimosa' and 'interfaces' in values:
        ports = [port for port in values['interfaces'].values() if port.get('type') == 6]
        named = [port for port in ports if str(port.get('name', '')).lower() == 'ether1']
        selected = named[0] if len(named) == 1 else ports[0] if len(ports) == 1 else None
        result['ethernet_traffic'] = ({key: selected[key]
            for key in ('name', 'speed_mbps', 'tx_bps', 'rx_bps') if key in selected}
            if selected and selected.get('status') == 1 and selected.get('admin_status') != 2 else {})
    if 'wireless_ssids' in result:
        names = result['wireless_ssids']
        names = [name for name in names if isinstance(name, str) and name.strip()] if isinstance(names, list) else []
        if names:
            result['wireless_ssids'] = names
        else:
            # Empty walks can mean unsupported OIDs or a timeout after uptime succeeded.
            result.pop('wireless_ssids')
    if 'wireless_clients' in result:
        count = result['wireless_clients']
        if isinstance(count, bool) or not isinstance(count, (int, float)) or not math.isfinite(count) or count < 0:
            result.pop('wireless_clients')
    if 'ethernet_links' in result:
        links = result['ethernet_links']
        links = [port for port in links if isinstance(port, dict)
                 and isinstance(port.get('speed_mbps'), (int, float))
                 and math.isfinite(port['speed_mbps']) and port['speed_mbps'] > 0] if isinstance(links, list) else []
        def has_ether1(ports):
            return any(str(port.get('name', '')).lower() == 'ether1' for port in ports)
        saved = (previous or {}).get('ethernet_links', {}).get('value', [])
        if not links or (has_ether1(saved) and not has_ether1(links)):
            # This inventory column shows ether1. A partial walk of other ports
            # must not discard its last measured speed or advance its timestamp.
            result.pop('ethernet_links')
        else:
            result['ethernet_links'] = links
    return result


def remember(db, device, values, timestamp):
    snapshot = db.get(DeviceTelemetrySnapshot, device.id)
    # Resetting live monitoring after an edit must not erase display history.
    fields = dict(snapshot.fields) if snapshot else {}
    history = remember_clients(fields.get(HISTORY_KEY), values, timestamp, device.ip_address)
    if history:
        fields[HISTORY_KEY] = history
    if values.get('icmp_up') or values.get('snmp_up') or values.get('api_up'):
        vendor = device.vendor if device.vendor != 'generic' else values.get('detected_vendor', 'generic')
        fields.update({key: {'value': value, 'observed_at': aware(timestamp).isoformat(),
                            'address': device.ip_address}
                       for key, value in readings(values, vendor, fields).items()})
    if snapshot:
        if snapshot.fields != fields:
            snapshot.fields = fields
    elif fields:
        db.add(DeviceTelemetrySnapshot(device_id=device.id, fields=fields))


def display(device, metric, snapshot, fresh, vendor):
    fields = dict(snapshot.fields) if snapshot else {}
    fields.pop(HISTORY_KEY, None)
    current = readings(metric.values, vendor, fields) if metric and device.last_poll else {}
    # Support existing samples before the first snapshot is collected as well.
    if current:
        fields.update({key: {'value': value, 'observed_at': aware(metric.collected_at).isoformat(),
                            'address': device.ip_address}
                       for key, value in current.items()})
    timestamps = {key: entry['observed_at'] for key, entry in fields.items()}
    stale = [key for key in fields if not fresh or key not in current]
    telemetry = {key: entry['value'] for key, entry in fields.items()}
    telemetry.setdefault('ethernet_links', [])
    return {'telemetry': telemetry, 'telemetry_at': max(timestamps.values(), default=None),
            'telemetry_stale_fields': stale, 'telemetry_field_times': timestamps,
            'telemetry_field_addresses': {key: entry['address'] for key, entry in fields.items() if entry.get('address')}}
