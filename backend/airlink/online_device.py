"""Session-verified customer device login and explicit configuration changes."""
import asyncio
from typing import Optional, Literal
from urllib.parse import urljoin, urlsplit
import json
import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator
from . import device_api, device_access, sas4, sas4_reports, device_login_profiles, device_management, routeros_native
from .customer_probes import valid_address
from .db import get_db
from .models import now, audit
from .schemas import WirelessSSIDInput

class DeviceRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()
        async def safe_validation(request):
            try:
                return await handler(request)
            except RequestValidationError:
                # FastAPI's default errors echo invalid inputs, including submitted passwords.
                return JSONResponse(status_code=422, content={'detail':
                    'Invalid device login or setting. Check required fields, credentials, port, IP prefixes, numeric values and SSID (1–32 UTF-8 bytes).'},
                    headers={'Cache-Control': 'no-store'})
        return safe_validation


router = APIRouter(prefix='/api/integrations/sas4', tags=['Online device'], route_class=DeviceRoute)


def short(value):
    return str(value)[:160] if isinstance(value, (str, int, float)) else None


def rows(value):
    return [row for row in value[:16] if isinstance(row, dict)] if isinstance(value, list) else []


async def routeros(client, base, config, reader=None):
    auth = httpx.BasicAuth(config['api_username'], config['api_password'])

    async def read(path, payload=None):
        if reader is not None:
            return await reader(path, payload)
        status, raw = await device_api.request(client, 'GET' if payload is None else 'POST',
            base + '/rest/' + path, auth=auth, **({} if payload is None else {'json': payload}))
        if status in (401, 403):
            raise PermissionError()
        return json.loads(raw) if status == 200 else None

    if config.get('tower_panel'):
        from .tower_routeros import snapshot
        return await snapshot(read)

    async def monitor(path, row):
        if not isinstance(row.get('.id'), str):
            return {}
        data = rows(await read(path + '/monitor', {'numbers': row['.id'], 'once': ''}))
        return data[0] if data else {}

    ports = await read('interface/ethernet?.proplist=.id,name,running,disabled')
    if not isinstance(ports, list):
        raise ValueError('RouterOS REST is unavailable')
    ethernet = []
    for port in rows(ports):
        state = await monitor('interface/ethernet', port)
        ethernet.append({'name': short(port.get('name')), 'status': short(state.get('status')),
                         'speed_mbps': device_api.rate(state.get('rate'))})
    wireless, registrations, settings = [], [], []
    for family in ('wireless', 'wifi', 'wifiwave2'):
        path = 'interface/' + family
        radios = await read(path + '?.proplist=.id,name,ssid,configuration.ssid,dynamic,configuration.manager')
        for radio in rows(radios):
            ssid = radio.get('ssid') if family == 'wireless' else radio.get('configuration.ssid')
            settings.append({'menu': family, 'id': short(radio.get('.id')), 'name': short(radio.get('name')),
                'ssid': short(ssid), 'editable': isinstance(ssid, str) and radio.get('dynamic') not in (True, 'true')
                and radio.get('configuration.manager', 'local') == 'local'})
            state = await monitor(path, radio)
            wireless.append({'name': short(radio.get('name')),
                'ssid': short(state.get('ssid') or radio.get('ssid') or radio.get('configuration.ssid')),
                'status': short(state.get('status')),
                'signal_dbm': device_api.signal(state.get('signal-strength') or state.get('signal'))})
        if wireless:
            # A single registration can describe a station uplink. Multiple peers cannot.
            registrations = await read(path + '/registration-table?.proplist=interface,mac-address,signal,signal-strength,uptime,tx-rate,rx-rate') or []
            for radio in wireless:
                peers = [r for r in registrations if isinstance(r, dict) and r.get('interface') == radio['name']] if isinstance(registrations, list) else []
                if len(peers) == 1 and radio['signal_dbm'] is None:
                    radio['signal_dbm'] = device_api.signal(peers[0].get('signal-strength') or peers[0].get('signal'))
            break
    if config.get('telemetry_only'):
        return {'vendor': 'MikroTik', 'wireless': wireless, 'ethernet': ethernet}
    pppoe_data = await read('interface/pppoe-client?.proplist=.id,name,interface,user,disabled,running')
    pppoe = []
    for item in rows(pppoe_data):
        state = await monitor('interface/pppoe-client', item)
        pppoe.append({'name': short(item.get('name')), 'interface': short(item.get('interface')),
            'username': short(item.get('user')),
            'status': short(state.get('status')) or ('disabled' if item.get('disabled') in (True, 'true') else 'Unavailable'),
            **{key: short(state.get(key)) for key in ('uptime', 'local-address', 'remote-address', 'ac-name')}})
    groups = {}
    for label, path, fields in (
        ('System', 'system/resource', 'version,board-name,architecture-name,uptime,cpu-load,free-memory,total-memory,free-hdd-space,total-hdd-space'),
        ('Identity', 'system/identity', 'name'),
        ('IP addresses', 'ip/address', 'address,network,interface,disabled,dynamic'),
        ('DNS', 'ip/dns', 'servers,dynamic-servers,allow-remote-requests'),
        ('Routes', 'ip/route', 'dst-address,gateway,distance,active,disabled'),
        ('Bridge ports', 'interface/bridge/port', 'interface,bridge,pvid,disabled'),
        ('VLANs', 'interface/vlan', 'name,interface,vlan-id,disabled'),
    ):
        content = await read(path + '?.proplist=' + fields)
        content = [content] if isinstance(content, dict) else content
        groups[label] = [{key: short(item[key]) for key in fields.split(',') if key in item} for item in rows(content)]
    clients = [{key: short(item.get(key)) for key in ('interface', 'mac-address', 'signal', 'signal-strength', 'uptime', 'tx-rate', 'rx-rate')}
               for item in registrations[:256] if isinstance(item, dict)] if isinstance(registrations, list) else []
    return {'vendor': 'MikroTik', 'wireless': wireless, 'ethernet': ethernet, 'pppoe': pppoe,
            'settings': settings, 'groups': groups, 'registrations': clients,
            'settings_note': 'SSID can be edited here. Other settings are available in the device web interface.',
            'pppoe_note': None if isinstance(pppoe_data, list) else 'PPPoE details are unavailable from this device API.'}


async def collect(address, config, transport=None):
    if config.get('transport') == 'auto':
        from .online_device_auto import detect_and_connect
        return await asyncio.wait_for(detect_and_connect(address, config, transport), timeout=60)
    result = await asyncio.wait_for(collect_once(address, config, transport), timeout=60 if config.get('tower_panel') else 25)
    return with_connection(result, config)


def with_connection(result, config):
    connection = {key: config[key] for key in ('transport', 'protocol', 'port', 'verify_tls', 'ssh_fingerprint') if config.get(key) is not None}
    connection.setdefault('transport', 'web')
    if result.get('web_url'):
        connection['protocol'] = urlsplit(result['web_url']).scheme
    return {**result, 'connection': connection}


async def branding(client, base):
    url = base + '/'
    for _ in range(3):
        async with client.stream('GET', url) as response:
            if response.status_code in (301, 302, 303, 307, 308):
                target = urljoin(url, response.headers.get('location', ''))
                if (urlsplit(target).scheme, urlsplit(target).netloc) != (urlsplit(base).scheme, urlsplit(base).netloc):
                    return '', ''
                url = target
                continue
            if response.status_code != 200:
                return '', ''
            raw = bytearray()
            async for chunk in response.aiter_bytes():
                raw.extend(chunk)
                if len(raw) > device_api.MAX_RESPONSE:
                    raise ValueError('Device response too large')
            return raw.decode('utf-8', errors='ignore').lower(), urlsplit(url).path
    return '', ''


def airmax_branding(page, path=''):
    """Recognize airOS M/AC login pages before sending device credentials."""
    if path.rstrip('/').lower() == '/login.cgi':
        return True
    return any(marker in page for marker in (
        'ubiquiti', 'ubnt', 'airos', 'airmax',
        'nanostation m', 'nanostation loco m', 'nanobeam m',
        'rocket m', 'powerbeam m', 'bullet m',
        'nanostation 5ac', 'nanobeam 5ac', 'powerbeam 5ac',
        'rocket 5ac', 'litebeam 5ac',
    ))


async def collect_once(address, config, transport=None):
    if config.get('transport') in ('routeros', 'routeros_tls'):
        async with routeros_native.Connection(address, config) as connection:
            return await routeros(None, '', config, reader=connection.read)
    if config.get('transport') == 'airos_ssh':
        from . import airos_management
        return await asyncio.to_thread(airos_management.connect, address, config)
    host = '[' + address + ']' if ':' in address else address
    schemes = ['https', 'http'] if config.get('protocol') == 'both' else [config.get('protocol', 'https')]
    for scheme in schemes:
        base = scheme + '://' + host + (':' + str(config['port']) if config.get('port') else '')
        async with httpx.AsyncClient(timeout=httpx.Timeout(2, connect=1), follow_redirects=False,
                trust_env=False, verify=config.get('verify_tls', True), transport=transport) as client:
            try:
                page, landing_path = await branding(client, base)
                if 'mikrotik' in page or 'routeros' in page or config.get('vendor_hint') == 'mikrotik':
                    result = await routeros(client, base, config)
                    return {**result, 'web_url': base}
                if airmax_branding(page, landing_path) or config.get('vendor_hint', '').startswith('ubiquiti'):
                    data = await device_api.airos(client, base, config, inventory=True)
                    return {'vendor': 'Ubiquiti', 'wireless': [
                        {'name': 'Wireless', 'ssid': ', '.join(data.get('wireless_ssids', [])),
                         'signal_dbm': data.get('signal_dbm')}],
                        'ethernet': [{**port, 'status': 'link-ok'} for port in data['ethernet_links']],
                        'pppoe': [], 'pppoe_note': 'PPPoE details are not exposed by the airOS status API.',
                        'web_url': base,
                        'groups': {'System': [{k: short(v) for k, v in data.items() if k in (
                            'device_model', 'firmware_version', 'uptime_seconds', 'cpu_percent', 'memory_percent', 'wireless_clients')}]},
                        'registrations': data.get('wireless_registrations', []),
                        'detected_vendor': data.get('detected_vendor', 'ubiquiti'),
                        'settings_note': 'For M5 / AC SSID editing, select Ubiquiti SSH. Full settings are in the device web interface.'}
            except PermissionError:
                raise
            except (httpx.HTTPError, ValueError, TypeError, KeyError):
                continue
    raise RuntimeError('No supported device API responded. Enable RouterOS REST or airOS web access and check the saved connection settings.')


def target(db, user, username, address, session_id, profile_id=None, manual=None, online_login=False):
    connection, password = sas4.local_user_connection(db, user)
    found = []
    for page in range(1, 6):
        result = sas4.fetch_clients(connection, password, page=page, search=username, count=100, online=True)
        found.extend(row for row in result['clients'] if row.get('username') == username
                     and valid_address(row.get('ip_address')) == address
                     and (session_id is None or str(row.get('session_id')) == session_id))
        if page >= result['last_page']:
            break
    else:
        raise HTTPException(409, 'Cannot uniquely verify this online session. Narrow the user search and retry.')
    if len(found) != 1:
        raise HTTPException(409, 'This online session changed or ended. Refresh Online Users and try again.')
    if manual is not None:
        return manual, 'Temporary login'
    if online_login:
        from .customer_probes import configuration
        config = configuration(db, user)
        if not config.get('enabled') or not config.get('api_username') or not config.get('api_password'):
            raise HTTPException(409, 'Save the device username and password in Device login in the sidebar.')
        return {**config, 'transport': 'auto', 'protocol': 'both' if config.get('allow_http') else 'https'}, 'Online users device login'
    if profile_id:
        return device_login_profiles.selected_configuration(db, user, profile_id)
    managers = sas4_reports.fetch_managers(connection, password)
    matches = [manager for manager in managers if manager['username'] == found[0].get('manager')]
    config = device_access.manager_configuration(db, user, matches[0]['id']) if len(matches) == 1 else None
    if not config or not config.get('enabled') or not config.get('api_username') or not config.get('api_password'):
        raise HTTPException(409, 'Add or enable this SAS4 manager’s login in Settings → Device API logins.')
    return config, matches[0]['username']


@router.get('/online-device')
def overview(username: str = Query(min_length=1, max_length=200),
             ip_address: str = Query(min_length=1, max_length=64),
             session_id: Optional[str] = Query(default=None, max_length=128),
             profile_id: Optional[str] = Query(default=None, min_length=1, max_length=36),
             user=Depends(sas4.sas4_access), db=Depends(get_db)):
    address = valid_address(ip_address)
    if not address:
        raise HTTPException(422, 'Invalid device IP address')
    try:
        config, manager = target(db, user, username, address, session_id, profile_id)
        data = asyncio.run(collect(address, config))
    except sas4.SAS4Error as exc:
        raise HTTPException(502, 'Could not verify the current SAS4 online session.') from exc
    except PermissionError as exc:
        raise HTTPException(502, 'Device login rejected. Check Settings → Device API logins and the device read permissions.') from exc
    except (TimeoutError, asyncio.TimeoutError) as exc:
        raise HTTPException(504, 'Device readings timed out. Check device access and retry.') from exc
    except RuntimeError as exc:
        raise HTTPException(502, str(exc)) from exc
    return {**data, 'username': username, 'ip_address': address, 'credential_source': manager,
            'fetched_at': now().isoformat()}


class TemporaryLogin(BaseModel):
    model_config = ConfigDict(extra='forbid')
    username: str = Field(min_length=1, max_length=128)
    password: SecretStr = Field(min_length=1, max_length=1024)
    transport: Literal['auto', 'web', 'routeros', 'routeros_tls', 'airos_ssh'] = 'web'
    protocol: Literal['https', 'http', 'both'] = 'both'
    port: Optional[int] = Field(default=None, ge=1, le=65535)
    verify_tls: Literal[True] = True
    ssh_fingerprint: Optional[str] = Field(default=None, pattern=r'^SHA256:[A-Za-z0-9+/]{43}$')
    snmp_community: SecretStr = Field(default='public', min_length=1, max_length=128)

    def configuration(self):
        return {**self.model_dump(exclude={'username', 'password', 'snmp_community'}), 'enabled': True,
            'snmp_community': self.snmp_community.get_secret_value() if isinstance(self.snmp_community, SecretStr) else self.snmp_community,
            'api_username': self.username, 'api_password': self.password.get_secret_value()}


class DeviceLogin(BaseModel):
    model_config = ConfigDict(extra='forbid')
    username: str = Field(min_length=1, max_length=200)
    ip_address: str = Field(min_length=1, max_length=64)
    session_id: Optional[str] = Field(default=None, max_length=128)
    profile_id: Optional[str] = Field(default=None, min_length=1, max_length=36)
    login: Optional[TemporaryLogin] = None
    use_online_login: bool = False
    ssh_fingerprint: Optional[str] = Field(default=None, pattern=r'^SHA256:[A-Za-z0-9+/]{43}$')

    @model_validator(mode='after')
    def single_source(self):
        if sum((self.login is not None, bool(self.profile_id), self.use_online_login)) > 1:
            raise ValueError('Choose a temporary login or a saved profile')
        return self


class ResolvedConnection(BaseModel):
    model_config = ConfigDict(extra='forbid')
    transport: Literal['web', 'routeros', 'routeros_tls', 'airos_ssh']
    protocol: Literal['https', 'http', 'both'] = 'https'
    port: Optional[int] = Field(default=None, ge=1, le=65535)
    verify_tls: bool = True
    ssh_fingerprint: Optional[str] = Field(default=None, pattern=r'^SHA256:[A-Za-z0-9+/]{43}$')


class DeviceChange(DeviceLogin):
    change: WirelessSSIDInput
    restart_radio: bool = False
    connection: Optional[ResolvedConnection] = None


def resolve_login(data, db, user):
    address = valid_address(data.ip_address)
    if not address:
        raise HTTPException(422, 'Invalid device IP address')
    try:
        config, source = target(db, user, data.username, address, data.session_id, data.profile_id,
                                data.login.configuration() if data.login else None, data.use_online_login)
    except sas4.SAS4Error:
        raise HTTPException(502, 'Could not verify the current SAS4 online session.') from None
    return address, config, source


@router.post('/online-device/login')
def login_device(data: DeviceLogin, user=Depends(sas4.sas4_access), db=Depends(get_db)):
    address, config, source = resolve_login(data, db, user)
    config = {**config, 'verify_tls': True}
    if data.login is None and config.get('transport') not in ('routeros', 'routeros_tls'):
        config = {**config, 'transport': 'auto', 'ssh_fingerprint': data.ssh_fingerprint}
    try:
        result = asyncio.run(collect(address, config))
    except PermissionError:
        raise HTTPException(502, 'Device login rejected. Check the username, password and device permissions.') from None
    except device_management.ManagementError as exc:
        raise HTTPException(exc.status, str(exc)) from None
    except (TimeoutError, asyncio.TimeoutError):
        raise HTTPException(504, 'Device connection timed out. Check the service and port.') from None
    except (OSError, routeros_native.APIError, ValueError):
        raise HTTPException(502, 'Device API connection failed. Check the selected connection type and port.') from None
    except RuntimeError as exc:
        raise HTTPException(502, str(exc)) from None
    return {**result, 'username': data.username, 'ip_address': address, 'credential_source': source,
            'fetched_at': now().isoformat()}


async def native_change(address, config, change):
    async with routeros_native.Connection(address, config) as connection:
        path = 'interface/' + change['menu']
        radios = await connection.read(path + '?.proplist=.id,ssid,configuration.ssid,dynamic,configuration.manager')
        radio = next((r for r in (radios or []) if r.get('.id') == change['radio_id']), None)
        field = 'ssid' if change['menu'] == 'wireless' else 'configuration.ssid'
        if not radio or radio.get(field) != change['previous_ssid']:
            raise device_management.ManagementError('Wireless settings changed. Reconnect before saving.', 409)
        if radio.get('dynamic') in (True, 'true') or radio.get('configuration.manager', 'local') != 'local':
            raise device_management.ManagementError('This radio is managed by its controller.', 409)
        if radio[field] == change['ssid']:
            return {'status': 'unchanged'}
        try:
            await connection.command('/' + path + '/set', {'.id': change['radio_id'], field: change['ssid']})
        except (OSError, routeros_native.APIError, asyncio.TimeoutError):
            raise device_management.ManagementError('Save result is unknown. Reconnect and verify before retrying.', 504) from None
        return {'status': 'accepted'}


@router.put('/online-device/settings')
def save_device(data: DeviceChange, user=Depends(sas4.sas4_access), db=Depends(get_db)):
    from contextlib import suppress
    from redis.exceptions import RedisError
    from . import api, section_access
    section_access.require_any(user, ('isp_card',), write=True)
    address, config, _ = resolve_login(data, db, user)
    if data.connection:
        config = {**config, **data.connection.model_dump()}
    config['verify_tls'] = True
    if config.get('transport') == 'auto':
        raise HTTPException(409, 'Connect first so settings are saved through the detected connection.')
    if config.get('transport') == 'airos_ssh' and not data.restart_radio:
        raise HTTPException(422, 'Saving airOS settings requires the Save SSID and restart radio action.')
    try:
        lock = api.cache.lock('online-device-change:' + address, timeout=60, blocking_timeout=0)
        if not lock.acquire(blocking=False):
            raise HTTPException(409, 'Another change is running on this device')
    except RedisError:
        raise HTTPException(503, 'Device change coordination is unavailable') from None
    try:
        audit(db, user, 'online_device.ssid.requested', address)
        db.commit()
        if config.get('transport') in ('routeros', 'routeros_tls'):
            result = asyncio.run(native_change(address, config, data.change.model_dump()))
        elif config.get('transport') == 'airos_ssh':
            from . import airos_management
            result = airos_management.connect(address, config, data.change.model_dump())
        else:
            result = device_management.run(address, config, data.change.model_dump())
        audit(db, user, 'online_device.ssid.' + result['status'], address)
        db.commit()
        return result
    except (device_management.ManagementError, PermissionError, OSError, routeros_native.APIError, asyncio.TimeoutError) as exc:
        audit(db, user, 'online_device.ssid.failed_or_unknown', address)
        db.commit()
        if isinstance(exc, device_management.ManagementError):
            raise HTTPException(exc.status, str(exc)) from None
        raise HTTPException(502, 'Device login or configuration change failed. Reconnect before retrying.') from None
    finally:
        with suppress(Exception):
            lock.release()
