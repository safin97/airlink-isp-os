"""Read-only customer device access using account-scoped, saved API logins."""
import asyncio
from typing import Optional
from urllib.parse import urljoin, urlsplit
import json
import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from . import device_api, device_access, sas4, sas4_reports, device_login_profiles
from .customer_probes import valid_address
from .db import get_db
from .models import now

router = APIRouter(prefix='/api/integrations/sas4', tags=['Online device'])


def short(value):
    return str(value)[:160] if isinstance(value, (str, int, float)) else None


def rows(value):
    return [row for row in value[:16] if isinstance(row, dict)] if isinstance(value, list) else []


async def routeros(client, base, config):
    auth = httpx.BasicAuth(config['api_username'], config['api_password'])

    async def read(path, payload=None):
        status, raw = await device_api.request(client, 'GET' if payload is None else 'POST',
            base + '/rest/' + path, auth=auth, **({} if payload is None else {'json': payload}))
        if status in (401, 403):
            raise PermissionError()
        return json.loads(raw) if status == 200 else None

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
    wireless = []
    for family in ('wireless', 'wifi', 'wifiwave2'):
        path = 'interface/' + family
        radios = await read(path + '?.proplist=.id,name,ssid,configuration.ssid')
        for radio in rows(radios):
            state = await monitor(path, radio)
            wireless.append({'name': short(radio.get('name')),
                'ssid': short(state.get('ssid') or radio.get('ssid') or radio.get('configuration.ssid')),
                'status': short(state.get('status')),
                'signal_dbm': device_api.signal(state.get('signal-strength') or state.get('signal'))})
        if wireless:
            # A single registration can describe a station uplink. Multiple peers cannot.
            registrations = await read(path + '/registration-table?.proplist=interface,signal,signal-strength')
            for radio in wireless:
                peers = [r for r in registrations if isinstance(r, dict) and r.get('interface') == radio['name']] if isinstance(registrations, list) else []
                if len(peers) == 1 and radio['signal_dbm'] is None:
                    radio['signal_dbm'] = device_api.signal(peers[0].get('signal-strength') or peers[0].get('signal'))
            break
    pppoe_data = await read('interface/pppoe-client?.proplist=.id,name,interface,user,disabled,running')
    pppoe = []
    for item in rows(pppoe_data):
        state = await monitor('interface/pppoe-client', item)
        pppoe.append({'name': short(item.get('name')), 'interface': short(item.get('interface')),
            'username': short(item.get('user')),
            'status': short(state.get('status')) or ('disabled' if item.get('disabled') in (True, 'true') else 'Unavailable'),
            **{key: short(state.get(key)) for key in ('uptime', 'local-address', 'remote-address', 'ac-name')}})
    return {'vendor': 'MikroTik', 'wireless': wireless, 'ethernet': ethernet, 'pppoe': pppoe,
            'pppoe_note': None if isinstance(pppoe_data, list) else 'PPPoE details are unavailable from this device API.'}


async def collect(address, config, transport=None):
    return await asyncio.wait_for(collect_once(address, config, transport), timeout=25)


async def branding(client, base):
    url = base + '/'
    for _ in range(3):
        async with client.stream('GET', url) as response:
            if response.status_code in (301, 302, 303, 307, 308):
                target = urljoin(url, response.headers.get('location', ''))
                if (urlsplit(target).scheme, urlsplit(target).netloc) != (urlsplit(base).scheme, urlsplit(base).netloc):
                    return ''
                url = target
                continue
            if response.status_code != 200:
                return ''
            raw = bytearray()
            async for chunk in response.aiter_bytes():
                raw.extend(chunk)
                if len(raw) > device_api.MAX_RESPONSE:
                    raise ValueError('Device response too large')
            return raw.decode('utf-8', errors='ignore').lower()
    return ''


async def collect_once(address, config, transport=None):
    host = '[' + address + ']' if ':' in address else address
    schemes = ['https', 'http'] if config.get('protocol') == 'both' else [config.get('protocol', 'https')]
    for scheme in schemes:
        base = scheme + '://' + host + (':' + str(config['port']) if config.get('port') else '')
        async with httpx.AsyncClient(timeout=httpx.Timeout(2, connect=1), follow_redirects=False,
                trust_env=False, verify=config.get('verify_tls', True), transport=transport) as client:
            try:
                page = await branding(client, base)
                if 'mikrotik' in page or 'routeros' in page:
                    return await routeros(client, base, config)
                if any(name in page for name in ('ubiquiti', 'ubnt', 'airos')):
                    data = await device_api.airos(client, base, config, inventory=True)
                    return {'vendor': 'Ubiquiti', 'wireless': [
                        {'name': 'Wireless', 'ssid': ', '.join(data.get('wireless_ssids', [])),
                         'signal_dbm': data.get('signal_dbm')}],
                        'ethernet': [{**port, 'status': 'link-ok'} for port in data['ethernet_links']],
                        'pppoe': [], 'pppoe_note': 'PPPoE details are not exposed by the airOS status API.'}
            except PermissionError:
                raise
            except (httpx.HTTPError, ValueError, TypeError, KeyError):
                continue
    raise RuntimeError('No supported device API responded. Enable RouterOS REST or airOS web access and check the saved connection settings.')


def target(db, user, username, address, session_id, profile_id=None):
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
