"""Bounded public wireless registration fields; never expose raw device records."""
import re
from datetime import datetime
from .client_telemetry import number
from .security import aware

HISTORY_KEY = '_registration_history'
HISTORY_LIMIT = 4096


def remember_clients(previous, values, timestamp, address):
    """Retain first-seen order; only a complete list proves a client left."""
    history = dict(previous or {})
    source = values.get('wireless_registration_source')
    successful = values.get('snmp_up') if source == 'SNMP' else values.get('api_up')
    if not source or not successful or not isinstance(values.get('wireless_registrations'), list):
        return history
    stamp = aware(timestamp).isoformat()
    rows = [dict(row) for row in history.get('clients', [])]
    known = {row['mac_address']: row for row in rows}
    current = {row['mac_address']: row for row in public_clients(values['wireless_registrations'])}
    complete = (values.get('wireless_registrations_complete') is True and
                len(public_clients(values['wireless_registrations'])) == len(values['wireless_registrations']) and
                values.get('wireless_clients', len(current)) == len(current))
    # Preserve rows through address changes, but never infer disconnection from
    # a different device's list until that MAC has been observed there.
    for row in rows:
        if complete and row.get('address') == address and row['mac_address'] not in current:
            if row['last_status'] != 'down':
                row['status_since'] = stamp
            row.update(last_status='down', checked_at=stamp)
    for mac in sorted(current):
        observed = current[mac]
        row = known.get(mac)
        if row is None:
            if len(rows) >= HISTORY_LIMIT:
                history['limited'] = True
                continue
            row = {'mac_address': mac, 'first_seen': stamp}
            rows.append(row)
        if row.get('last_status') != 'up' or row.get('address') != address:
            row['status_since'] = stamp
        row.update({key: value for key, value in observed.items() if value is not None and value != ''})
        row.update(last_status='up', last_seen=stamp, checked_at=stamp, address=address)
    history.update(clients=rows, collected_at=stamp, source=source, complete=complete,
                   total=values.get('wireless_clients'))
    return history


def client_history_view(history, device, timestamp, confirmed_at=None):
    result = []
    for saved in history.get('clients', []):
        row = dict(saved)
        fresh = bool(device.enabled and device.last_poll and device.status != 'offline' and
                     confirmed_at and aware(datetime.fromisoformat(row['checked_at'])) == aware(confirmed_at) and
                     row.get('address') == device.ip_address and
                     (aware(timestamp) - aware(datetime.fromisoformat(row['checked_at']))).total_seconds()
                     <= device.poll_interval * 3 + 30)
        row['status'] = row['last_status'] if fresh else 'unknown'
        result.append(row)
    return result


def registration_state(device, metric, snapshot, timestamp):
    """One status calculation for the device count and the registration list."""
    fresh = bool(device.enabled and device.last_poll and metric and
                 (aware(timestamp) - aware(metric.collected_at)).total_seconds() <= device.poll_interval * 3 + 30)
    values = metric.values if fresh else {}
    history = (snapshot.fields.get(HISTORY_KEY) or {}) if snapshot else {}
    if fresh and not history:
        history = remember_clients({}, values, metric.collected_at, device.ip_address)
    source = values.get('wireless_registration_source')
    successful = values.get('snmp_up') if source == 'SNMP' else values.get('api_up')
    clients = client_history_view(history, device, timestamp, metric.collected_at if fresh and successful else None)
    if not history:
        clients = [{**row, 'status': 'unknown'} for row in public_clients(values.get('wireless_registrations'))]
    total = values.get('wireless_clients')
    available = bool(clients) or (source and total == 0)
    counts = ({'online': sum(row['status'] == 'up' for row in clients),
               'offline': sum(row['status'] == 'down' for row in clients),
               'unknown': sum(row['status'] not in ('up', 'down') for row in clients),
               'limited': bool(history.get('limited'))} if history or clients else None)
    return {'clients': clients, 'counts': counts,
            'total': total if total is not None else history.get('total'),
            'history_limited': bool(history.get('limited')),
            'status': 'available' if available else 'stale' if metric and not fresh else 'unavailable',
            'source': source or history.get('source'),
            'collected_at': metric.collected_at if fresh else history.get('collected_at')}


def mac_address(value):
    if not isinstance(value, str):
        return None
    raw = value.replace(':', '').replace('-', '')
    if not re.fullmatch(r'[0-9a-fA-F]{12}', raw):
        return None
    return ':'.join(raw[i:i+2] for i in range(0, 12, 2)).upper()


def username(value):
    return value if isinstance(value, str) and value.strip() and len(value) <= 200 and not any(ord(c) < 32 or ord(c) == 127 for c in value) else None


def username_map(rows):
    """Only exact MAC matches with one distinct username are attributable."""
    matches = {}
    for row in rows:
        mac, name = mac_address(row.get('mac_address')), username(row.get('username'))
        if mac and name:
            matches.setdefault(mac, set()).add(name)
    return {mac: next(iter(names)) if len(names) == 1 else None for mac, names in matches.items()}


def public_clients(rows):
    result = []
    if not isinstance(rows, list):
        return result
    for row in rows[:256]:
        if not isinstance(row, dict):
            continue
        mac = mac_address(row.get('mac_address'))
        if not mac:
            continue
        result.append({'mac_address': mac,
            'interface': str(row.get('interface') or '')[:120],
            'ssid': str(row.get('ssid') or '')[:128],
            'signal_dbm': row.get('signal_dbm') if number(row.get('signal_dbm'), -150, -.001) else None})
        if 'pppoe_username' in row:
            result[-1]['pppoe_username'] = username(row['pppoe_username'])
            result[-1]['pppoe_username_status'] = ('matched' if result[-1]['pppoe_username'] else
                'ambiguous' if row.get('pppoe_username_status') == 'ambiguous' else 'unavailable')
    return result


def ssids(values):
    return sorted({value[:128] for value in values if isinstance(value, str) and value})[:32]
