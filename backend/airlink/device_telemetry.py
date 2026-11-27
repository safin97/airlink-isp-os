"""Last known display readings. Never substitute these for live monitoring samples."""
import math
from .models import DeviceTelemetrySnapshot
from .security import aware
from .wireless_clients import HISTORY_KEY, remember_clients

FIELDS = ('cpu_percent', 'memory_percent', 'uptime_seconds', 'ethernet_links',
          'signal_dbm', 'weakest_signal_dbm', 'wireless_clients', 'radio_frequencies_mhz',
          'wireless_ssids', 'firmware_version', 'device_model', 'telemetry_source')
PORT_HISTORY_KEY = '_ethernet_port_history'
AUTO_PORT_KEY = '_ethernet_auto'


def automatic_port(ports, observed, previous=None):
    available = {port.get('name') for port in observed.get('ethernet_links', [])} & ports.keys()
    if available:
        preferred = (previous or {}).get('value', {}).get('name')
        name = min(available, key=lambda name: (name.casefold() != 'ether1', name != preferred, name.casefold(), name))
        return ports[name]
    # No new measurement: retain the automatically chosen port and its time.
    if previous:
        return previous
    if ports:
        return max(ports.values(), key=lambda entry: entry['observed_at'])
    return None


def port_history(fields, current=None, timestamp=None, address=None):
    """Keep each port's observation time even when another port is refreshed."""
    history = dict(fields.get(PORT_HISTORY_KEY, {}))
    saved = fields.get('ethernet_links', {})
    for port in saved.get('value', []):
        name = port.get('name')
        if isinstance(name, str) and name:
            history.setdefault(name, {**saved, 'value': port})
    for port in (current or {}).get('ethernet_links', []):
        name = port.get('name')
        if isinstance(name, str) and name:
            history[name] = {'value': port, 'observed_at': aware(timestamp).isoformat(), 'address': address}
    # Bound retained names, including interfaces renamed over time.
    return dict(sorted(history.items(), key=lambda item: item[1]['observed_at'])[-256:])


def port_choices(device, metric, snapshot):
    names = set(port_history(snapshot.fields if snapshot else {}))
    values = metric.values if metric and device.last_poll else {}
    names.update(port.get('name', str(index)) for index, port in values.get('interfaces', {}).items()
                 if port.get('type') == 6)
    names.update(port.get('name') for port in values.get('ethernet_links', []))
    if device.ethernet_speed_port:
        names.add(device.ethernet_speed_port)
    return sorted(name for name in names if isinstance(name, str) and 0 < len(name) <= 128)


def readings(values, vendor, previous=None):
    # Failed probes must not turn empty/default fields into fresh observations.
    states = [values[key] for key in ('icmp_up', 'snmp_up', 'api_up') if key in values]
    if states and not any(states) and values.get('api_status') != 'connected':
        return {}
    result = {key: values[key] for key in FIELDS if key in values and values[key] is not None}
    if 'interfaces' in values and 'ethernet_links' not in result:
        result['ethernet_links'] = [{'name': port.get('name', index), 'speed_mbps': port['speed_mbps']}
            for index, port in values['interfaces'].items()
            if port.get('type') == 6 and port.get('status') == 1
            and port.get('admin_status') != 2 and port.get('speed_mbps', 0) > 0]
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
                 and not isinstance(port['speed_mbps'], bool)
                 and math.isfinite(port['speed_mbps']) and port['speed_mbps'] > 0] if isinstance(links, list) else []
        def has_ether1(ports):
            return any(str(port.get('name', '')).lower() == 'ether1' for port in ports)
        saved = (previous or {}).get('ethernet_links', {}).get('value', [])
        if not links or (has_ether1(saved) and not has_ether1(links)):
            # Preserve the legacy summary. Automatic and explicit selection
            # use each port's independent observations below.
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
        current = readings(values, vendor, fields)
        observed = readings(values, vendor)
        ports = port_history(fields, observed, timestamp, device.ip_address)
        if ports:
            fields[PORT_HISTORY_KEY] = ports
        automatic = automatic_port(ports, observed, fields.get(AUTO_PORT_KEY))
        if automatic:
            fields[AUTO_PORT_KEY] = automatic
        fields.update({key: {'value': value, 'observed_at': aware(timestamp).isoformat(),
                            'address': device.ip_address}
                       for key, value in current.items()})
    if snapshot:
        if snapshot.fields != fields:
            snapshot.fields = fields
    elif fields:
        db.add(DeviceTelemetrySnapshot(device_id=device.id, fields=fields))


def display(device, metric, snapshot, fresh, vendor):
    fields = dict(snapshot.fields) if snapshot else {}
    fields.pop(HISTORY_KEY, None)
    current = readings(metric.values, vendor, fields) if metric and device.last_poll else {}
    observed = readings(metric.values, vendor) if metric and device.last_poll else {}
    ports = port_history(fields, observed, metric.collected_at if metric else None, device.ip_address)
    automatic = automatic_port(ports, observed, fields.pop(AUTO_PORT_KEY, None))
    fields.pop(PORT_HISTORY_KEY, None)
    # Support existing samples before the first snapshot is collected as well.
    if current:
        fields.update({key: {'value': value, 'observed_at': aware(metric.collected_at).isoformat(),
                            'address': device.ip_address}
                       for key, value in current.items()})
    timestamps = {key: entry['observed_at'] for key, entry in fields.items()}
    stale = [key for key in fields if not fresh or key not in current]
    selected = device.ethernet_speed_port
    if selected and selected in ports:
        fields['ethernet_selected'] = ports[selected]
        timestamps['ethernet_selected'] = ports[selected]['observed_at']
        if not fresh or not any(port.get('name') == selected for port in observed.get('ethernet_links', [])):
            stale.append('ethernet_selected')
    telemetry = {key: entry['value'] for key, entry in fields.items()}
    telemetry.setdefault('ethernet_links', [])
    return {'telemetry': telemetry, 'telemetry_at': max(timestamps.values(), default=None),
            'ethernet_auto': ({**automatic['value'], 'observed_at': automatic['observed_at'],
                               'address': automatic.get('address'),
                               'stale': not fresh or not any(port.get('name') == automatic['value']['name']
                                   for port in observed.get('ethernet_links', []))} if automatic else None),
            'telemetry_stale_fields': stale, 'telemetry_field_times': timestamps,
            'telemetry_field_addresses': {key: entry['address'] for key, entry in fields.items() if entry.get('address')}}
