"""Tower RouterOS inventory and explicit, allowlisted configuration changes."""
import asyncio
import ipaddress
import json
import re
from typing import Literal, Optional

import httpx
from pydantic import BaseModel, ConfigDict, Field, model_validator

from . import device_api, routeros_native
from .device_management import ManagementError

# No raw commands, security profiles, passwords or scripts are exposed by this panel.
DEFINITIONS = {
    'identity': ('Device identity', 'system/identity', [('name', 'Device name', 'text')]),
    'ethernet': ('Ethernet', 'interface/ethernet', [('name', 'Port name', 'text'), ('comment', 'Comment', 'text'), ('disabled', 'Disabled', 'bool'), ('auto-negotiation', 'Auto negotiation', 'bool'), ('mtu', 'MTU', 'number')]),
    'wireless': ('Wireless (legacy)', 'interface/wireless', [('name', 'Interface name', 'text'), ('ssid', 'SSID', 'ssid'), ('disabled', 'Disabled', 'bool'), ('frequency', 'Frequency', 'text'), ('mode', 'Mode', 'text')]),
    'wifi': ('Wireless (WiFi)', 'interface/wifi', [('name', 'Interface name', 'text'), ('configuration.ssid', 'SSID', 'ssid'), ('disabled', 'Disabled', 'bool'), ('channel.frequency', 'Frequency', 'text'), ('configuration.mode', 'Mode', 'text')]),
    'wifiwave2': ('Wireless (WiFi Wave2)', 'interface/wifiwave2', [('name', 'Interface name', 'text'), ('configuration.ssid', 'SSID', 'ssid'), ('disabled', 'Disabled', 'bool'), ('channel.frequency', 'Frequency', 'text'), ('configuration.mode', 'Mode', 'text')]),
    'addresses': ('IP addresses', 'ip/address', [('address', 'IPv4 address / prefix', 'text'), ('interface', 'Interface', 'interface'), ('disabled', 'Disabled', 'bool'), ('comment', 'Comment', 'text')]),
    'dns': ('DNS', 'ip/dns', [('servers', 'DNS servers (comma separated)', 'text'), ('allow-remote-requests', 'Allow remote requests', 'bool')]),
    'routes': ('Routes', 'ip/route', [('dst-address', 'Destination / prefix', 'text'), ('gateway', 'Gateway', 'text'), ('distance', 'Distance', 'number'), ('disabled', 'Disabled', 'bool'), ('comment', 'Comment', 'text')]),
}
SINGLETONS = {'identity', 'dns'}
CREATABLE = {'addresses', 'routes'}
GUARDS = ['dynamic', 'configuration.manager', 'slave']
ID = re.compile(r'\*[0-9a-fA-F]+\Z')


def items(value):
    if isinstance(value, dict):
        value = [value]
    if not isinstance(value, list):
        return []
    if len(value) > 4096:
        raise ValueError('Device table exceeds the supported size')
    return [r for r in value if isinstance(r, dict)]


def truth(value):
    return value is True or value == 'true'


def interface_status(row):
    if truth(row.get('disabled')):
        return 'disabled'
    if 'running' not in row:
        return 'unknown'
    return 'running' if truth(row['running']) else 'not running'


def clean(value):
    if isinstance(value, bool):
        return 'true' if value else 'false'
    return str(value)[:1024] if isinstance(value, (str, int, float)) else ''


def editable(resource, row):
    if truth(row.get('dynamic')):
        return False
    if resource in ('wireless', 'wifi', 'wifiwave2'):
        if row.get('configuration.manager', 'local') != 'local':
            return False
        # Never overwrite inherited wireless configuration through this editor.
        field = 'ssid' if resource == 'wireless' else 'configuration.ssid'
        if field not in row:
            return False
    return resource in SINGLETONS or bool(ID.fullmatch(str(row.get('.id', ''))))


def query(resource):
    _, path, fields = DEFINITIONS[resource]
    return path + '?.proplist=' + ','.join(['.id'] + [f[0] for f in fields] + GUARDS)


def numeric(value):
    try:
        number = float(value)
        return number if 0 <= number < 1e16 else None
    except (TypeError, ValueError):
        return None


async def snapshot(read):
    interfaces = await read('interface?.proplist=.id,name,type,running,disabled,rx-byte,tx-byte')
    if not isinstance(interfaces, list):
        raise ValueError('Device interfaces could not be read')
    interfaces = items(interfaces)
    traffic = items(await read('interface/monitor-traffic', {'interface': 'all', 'once': ''}))
    traffic_by_name = {r.get('name'): r for r in traffic if r.get('name')}
    state_by_name = {r.get('name'): r for r in interfaces}
    sections, raw_sections, warnings = [], {}, []
    seen_radios = set()
    wireless, registrations = [], []
    for resource, (title, path, fields) in DEFINITIONS.items():
        raw = await read(query(resource))
        if raw is None:
            if resource not in ('wireless', 'wifi', 'wifiwave2'):
                warnings.append(title + ' unavailable: check device API read permissions.')
            continue
        raw = items(raw)
        raw_sections[resource] = raw
        records = []
        for row in raw:
            if resource in ('wireless', 'wifi', 'wifiwave2'):
                if row.get('name') in seen_radios:
                    continue
                seen_radios.add(row.get('name'))
                ssid = row.get('ssid', row.get('configuration.ssid'))
                state = state_by_name.get(row.get('name'), row)
                rate = traffic_by_name.get(row.get('name'), {})
                wireless.append({'name': clean(row.get('name')), 'ssid': clean(ssid),
                    'status': interface_status(state),
                    'rx_bps': numeric(rate.get('rx-bits-per-second')), 'tx_bps': numeric(rate.get('tx-bits-per-second'))})
            values = {key: clean(row[key]) for key, _, _ in fields if key in row}
            records.append({'id': clean(row.get('.id')) if resource not in SINGLETONS else '',
                'values': values, 'editable': editable(resource, row),
                'reason': None if editable(resource, row) else 'Dynamic or inherited settings must be changed at their source.'})
        sections.append({'resource': resource, 'title': title,
            'fields': [{'key': k, 'label': label, 'kind': kind} for k, label, kind in fields],
            'rows': records, 'can_add': resource in CREATABLE, 'can_delete': resource in CREATABLE})
        if resource in ('wireless', 'wifi', 'wifiwave2'):
            peers = items(await read(path + '/registration-table?.proplist=interface,mac-address,signal,signal-strength,uptime,tx-rate,rx-rate'))
            for peer in peers:
                safe = {k: clean(peer[k]) for k in ('interface', 'mac-address', 'signal', 'signal-strength', 'uptime', 'tx-rate', 'rx-rate') if k in peer}
                if safe not in registrations:
                    registrations.append(safe)
    for radio in wireless:
        peers = [r for r in registrations if r.get('interface') == radio['name']]
        if len(peers) == 1:
            radio['signal_dbm'] = device_api.signal(peers[0].get('signal-strength') or peers[0].get('signal'))
    ports = raw_sections.get('ethernet', [])
    ids = [r['.id'] for r in ports if ID.fullmatch(str(r.get('.id', '')))]
    monitors = items(await read('interface/ethernet/monitor', {'numbers': ','.join(ids), 'once': ''})) if ids else []
    by_name = {r.get('name'): r for r in monitors if r.get('name')}
    by_id = {r.get('.id'): r for r in monitors if r.get('.id')}
    ethernet = []
    for port in ports:
        name = port.get('name')
        state = state_by_name.get(name, port)
        monitor = by_name.get(name, by_id.get(port.get('.id'), {}))
        if len(ports) == len(monitors) == 1:
            monitor = monitors[0]
        rate = traffic_by_name.get(name, {})
        ethernet.append({'name': clean(name),
            'status': interface_status(state),
            'speed_mbps': device_api.rate(monitor.get('rate')),
            'full_duplex': monitor.get('full-duplex'),
            'rx_bps': numeric(rate.get('rx-bits-per-second')), 'tx_bps': numeric(rate.get('tx-bits-per-second'))})
    system = items(await read('system/resource?.proplist=version,board-name,uptime,cpu-load,free-memory,total-memory'))
    if not traffic:
        warnings.append('Traffic readings unavailable. Unknown values are shown as —.')
    return {'vendor': 'MikroTik', 'ethernet': ethernet, 'wireless': wireless,
        'registrations': registrations, 'tower_settings': sections,
        'interfaces': [clean(r.get('name')) for r in interfaces if r.get('name')],
        'groups': {'System': [{k: clean(v) for k, v in r.items() if k in ('version', 'board-name', 'uptime', 'cpu-load', 'free-memory', 'total-memory')} for r in system]},
        'warnings': warnings}


class Change(BaseModel):
    model_config = ConfigDict(extra='forbid')
    profile_id: str = Field(min_length=1, max_length=36)
    resource: Literal['identity', 'ethernet', 'wireless', 'wifi', 'wifiwave2', 'addresses', 'dns', 'routes']
    action: Literal['set', 'add', 'remove'] = 'set'
    record_id: str = Field(default='', max_length=32)
    previous: dict[str, Optional[str]] = Field(default_factory=dict)
    changes: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode='after')
    def validate_change(self):
        fields = {key: kind for key, _, kind in DEFINITIONS[self.resource][2]}
        if set(self.previous) - fields.keys() or set(self.changes) - fields.keys():
            raise ValueError('Unsupported field')
        if self.action != 'set' and self.resource not in CREATABLE:
            raise ValueError('Unsupported action')
        if self.resource not in SINGLETONS and self.action != 'add' and not ID.fullmatch(self.record_id):
            raise ValueError('Invalid record ID')
        if (self.resource in SINGLETONS or self.action == 'add') and self.record_id:
            raise ValueError('Unexpected record ID')
        if self.action == 'remove' and self.changes:
            raise ValueError('Unexpected changes')
        if self.action != 'remove' and not self.changes:
            raise ValueError('No changes')
        for key, value in self.previous.items():
            if value is not None and len(value) > 1024:
                raise ValueError('Invalid previous value')
        for key, value in self.changes.items():
            if len(value) > 1024 or any(ord(c) < 32 for c in value):
                raise ValueError('Invalid value')
            kind = fields[key]
            if kind == 'bool' and value not in ('true', 'false'):
                raise ValueError('Invalid boolean')
            if kind == 'ssid' and not 1 <= len(value.encode('utf-8')) <= 32:
                raise ValueError('Invalid SSID')
            if key in ('name', 'interface') and not 1 <= len(value.encode()) <= 128:
                raise ValueError('Invalid name')
            if key in ('mtu', 'distance') and (not value.isdigit() or not (68 <= int(value) <= 65535 if key == 'mtu' else 1 <= int(value) <= 255)):
                raise ValueError('Invalid number')
            if key in ('address', 'dst-address'):
                if '/' not in value or ipaddress.ip_interface(value).version != 4:
                    raise ValueError('An IPv4 prefix is required')
            if key == 'servers' and value:
                for server in value.split(','):
                    ipaddress.ip_address(server.strip())
            if key == 'gateway' and (not value or len(value) > 256):
                raise ValueError('Invalid gateway')
        if self.action == 'set' and not set(self.changes) <= self.previous.keys():
            raise ValueError('Previous values required')
        if self.action == 'remove' and not self.previous:
            raise ValueError('Previous values required')
        if self.action == 'add':
            required = {'address', 'interface'} if self.resource == 'addresses' else {'dst-address', 'gateway'}
            if not required <= self.changes.keys():
                raise ValueError('Required fields missing')
        return self


async def apply(read, write, change):
    resource = change.resource
    path = DEFINITIONS[resource][1]
    current = await read(query(resource))
    if current is None:
        raise ManagementError('Settings could not be read. No change was sent.', 502)
    rows = items(current)
    if change.action != 'add':
        row = (rows[0] if rows else None) if resource in SINGLETONS else next((r for r in rows if r.get('.id') == change.record_id), None)
        if row is None or not editable(resource, row):
            raise ManagementError('Settings are missing, dynamic or controller managed. Refresh before editing.', 409)
        if change.action == 'remove':
            required = {key for key, _, _ in DEFINITIONS[resource][2] if key in row}
            if not required <= change.previous.keys():
                raise ManagementError('Reload the full record before deleting it.', 409)
        if any((clean(row[k]) if k in row else None) != v for k, v in change.previous.items()):
            raise ManagementError('Settings changed since they were opened. Refresh before saving.', 409)
        if change.action == 'set' and all(clean(row.get(k)) == v for k, v in change.changes.items()):
            return {'status': 'unchanged'}
    if 'interface' in change.changes:
        available = items(await read('interface?.proplist=name'))
        if change.changes['interface'] not in {r.get('name') for r in available}:
            raise ManagementError('The selected interface no longer exists. Refresh settings.', 409)
    attributes = {**change.changes}
    if change.record_id:
        attributes['.id'] = change.record_id
    try:
        await write(path + '/' + change.action, attributes)
    except (httpx.HTTPError, OSError, EOFError, asyncio.TimeoutError, ValueError):
        raise ManagementError('Save result is unknown. Reconnect and verify before retrying.', 504) from None
    return {'status': 'accepted'}


async def change_once(address, config, change, transport=None):
    if config.get('transport') in ('routeros', 'routeros_tls'):
        async with routeros_native.Connection(address, config) as connection:
            async def write(path, values):
                try:
                    return await connection.command('/' + path, values)
                except routeros_native.APIError:
                    raise ManagementError('Device rejected the change or disconnected. Refresh and check API write permissions before retrying.', 502) from None
            return await apply(connection.read, write, change)
    # Select a responding protocol with reads only. Never retry/fail over a write.
    host = '[' + address + ']' if ':' in address else address
    protocols = ['https', 'http'] if config.get('protocol') == 'both' else [config.get('protocol', 'https')]
    async with httpx.AsyncClient(timeout=5, trust_env=False, follow_redirects=False,
            verify=config.get('verify_tls', True), transport=transport) as client:
        auth = httpx.BasicAuth(config['api_username'], config['api_password'])
        base = None
        for protocol in protocols:
            candidate = protocol + '://' + host + (':' + str(config['port']) if config.get('port') else '') + '/rest/'
            try:
                status, raw = await device_api.request(client, 'GET', candidate + query(change.resource), auth=auth)
                if status in (401, 403):
                    raise PermissionError()
                if status == 200 and isinstance(json.loads(raw), (list, dict)):
                    base = candidate
                    break
            except (httpx.HTTPError, ValueError):
                continue
        if base is None:
            raise ManagementError('Settings could not be read. No change was sent.', 502)
        async def read(path, payload=None):
            status, raw = await device_api.request(client, 'GET', base + path, auth=auth)
            if status in (401, 403):
                raise PermissionError()
            return json.loads(raw) if status == 200 else None
        async def write(path, values):
            status, _ = await device_api.request(client, 'POST', base + path, auth=auth, json=values)
            if status not in (200, 201, 204):
                raise ManagementError('Device rejected the change. Refresh and check API write permissions before retrying.', 502)
        return await apply(read, write, change)


async def save(address, config, change):
    return await asyncio.wait_for(change_once(address, config, change), timeout=30)
