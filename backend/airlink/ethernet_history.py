"""Track ports observed in use and acknowledgements of individual link outages."""
from copy import deepcopy
from datetime import datetime
from .security import aware

KEY = '_ethernet_usage_history'
LIMIT = 256
DOWN_STATES = {2, 5, 6, 7}


def observations(values):
    ports = None
    if (values.get('snmp_up') is True and values.get('ethernet_ports_complete') is not False
            and isinstance(values.get('interfaces'), dict)):
        ports = [{**port, 'name': port.get('name', str(index))}
                 for index, port in values['interfaces'].items() if isinstance(port, dict)]
    if not ports and values.get('api_up') is True:
        ports = values.get('ethernet_port_states')
    if not isinstance(ports, list):
        return {}
    return {p['name']: p for p in ports if isinstance(p, dict) and p.get('type') == 6
            and isinstance(p.get('name'), str) and 0 < len(p['name']) <= 128}


def remember(fields, values, timestamp, address):
    history = deepcopy(fields.get(KEY) or {})
    current = observations(values)
    if not current or timestamp is None:
        return history
    stamp = aware(timestamp).isoformat()
    if history.get('address') != address:
        history = {'address': address, 'ports': {}}
    if history.get('observed_at') and aware(datetime.fromisoformat(history['observed_at'])) >= aware(timestamp):
        return history  # Re-reading a sample must never undo an acknowledgement.
    ports = history.setdefault('ports', {})
    # Previously retained positive link speeds are evidence the port was in use.
    saved = dict(fields.get('_ethernet_port_history') or {})
    old_links = fields.get('ethernet_links') or {}
    for link in old_links.get('value', []):
        saved.setdefault(link.get('name'), {**old_links, 'value': link})
    for name, port in current.items():
        if name not in ports and len(ports) >= LIMIT:
            history['limited'] = True
            continue
        row = ports.setdefault(name, {'used': False})
        old = saved.get(name, {})
        if (old.get('address') == address and old.get('observed_at') and
                aware(datetime.fromisoformat(old['observed_at'])) < aware(timestamp)):
            row['used'] = True
        state = ('down' if port.get('admin_status') == 2 else
                 'running' if port.get('status') == 1 else
                 'down' if port.get('status') in DOWN_STATES else 'unknown')
        if state == 'running':
            row.update(used=True, last_running=stamp)
            row.pop('down_since', None)
            row.pop('resolved_at', None)
        elif state == 'down' and row.get('used') and not row.get('down_since'):
            row['down_since'] = stamp
        row.update(state=state, observed_at=stamp)
    for name, row in ports.items():
        if name not in current:
            row.update(state='unknown', observed_at=stamp)
    history['observed_at'] = stamp
    return history


def status(row):
    if row.get('state') == 'running':
        return 'running'
    if row.get('state') != 'down':
        return 'unknown'
    if not row.get('used'):
        return 'unused'
    return 'resolved' if row.get('resolved_at') else 'down'


def counts_entry(history):
    if not history or not history.get('observed_at'):
        return None
    counts = {'online': 0, 'offline': 0, 'unknown': 0, 'unused': 0, 'resolved': 0}
    for row in history.get('ports', {}).values():
        state = status(row)
        counts[{'running': 'online', 'down': 'offline'}.get(state, state)] += 1
    return {'value': counts, 'observed_at': history['observed_at'], 'address': history['address']}
