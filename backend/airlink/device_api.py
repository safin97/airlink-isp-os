"""Bounded read-only RouterOS REST and legacy airOS status adapters."""
import json
import re
import httpx

MAX_RESPONSE = 1024 * 1024


async def request(client, method, url, **kwargs):
    async with client.stream(method, url, **kwargs) as response:
        chunks = bytearray()
        async for chunk in response.aiter_bytes():
            chunks.extend(chunk)
            if len(chunks) > MAX_RESPONSE:
                raise ValueError('Device response too large')
        return response.status_code, bytes(chunks)


def rate(value):
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r'\s*(\d+(?:\.\d+)?)\s*([kmg]?)bps\s*', value, re.I)
    if not match:
        return None
    amount = float(match[1]) * {'': .000001, 'k': .001, 'm': 1, 'g': 1000}[match[2].lower()]
    return amount if 0 < amount <= 1e9 else None


def signal(value):
    if isinstance(value, bool):
        return None
    match = re.fullmatch(r'\s*(-\d+(?:\.\d+)?)(?:\s*dBm)?(?:@[^\s]+)?\s*', str(value), re.I)
    if not match:
        return None
    value = float(match[1])
    return value if -150 <= value < 0 else None


async def routeros(client, base, credentials):
    auth = httpx.BasicAuth(credentials['api_username'], credentials['api_password'])
    async def read(path, payload=None):
        status, raw = await request(client, 'GET' if payload is None else 'POST', base + '/rest/' + path,
                                    auth=auth, **({} if payload is None else {'json': payload}))
        if status in (401, 403):
            raise PermissionError('Device API credentials rejected')
        if status != 200:
            return None
        return json.loads(raw)
    interfaces = await read('interface/ethernet?.proplist=.id,name')
    if not isinstance(interfaces, list):
        raise ValueError('Not a RouterOS REST API')
    links = []
    for port in interfaces[:16]:
        if not isinstance(port, dict) or not isinstance(port.get('.id'), str):
            continue
        data = await read('interface/ethernet/monitor', {'numbers': port['.id'], 'once': ''})
        if isinstance(data, list) and len(data) == 1 and isinstance(data[0], dict):
            speed = rate(data[0].get('rate'))
            if data[0].get('status') == 'link-ok' and speed:
                links.append({'name': str(port.get('name', port['.id']))[:120], 'speed_mbps': speed})
    strength = None
    for path, field in (('interface/wireless/registration-table', 'signal-strength'),
                        ('interface/wifi/registration-table', 'signal'),
                        ('interface/wifiwave2/registration-table', 'signal')):
        data = await read(path)
        if isinstance(data, list) and data:
            # More than one station cannot be attributed to this customer's link.
            strength = signal(data[0].get(field)) if len(data) == 1 and isinstance(data[0], dict) else None
            break
    return {'ethernet_links': links, 'signal_dbm': strength, 'telemetry_source': 'RouterOS API'}


def airos_values(data):
    if not isinstance(data, dict) or not isinstance(data.get('wireless'), dict):
        raise ValueError('Not an airOS status response')
    links = []
    ports = data.get('interfaces', [])
    if not isinstance(ports, list):
        ports = []
    for port in ports[:32]:
        if not isinstance(port, dict):
            continue
        name, status = port.get('ifname'), port.get('status')
        if not isinstance(name, str) or not re.fullmatch(r'eth\d+', name) or not isinstance(status, dict):
            continue
        speed = status.get('speed')
        if isinstance(speed, str) and speed.isdigit():
            speed = int(speed)
        if status.get('plugged') in (1, True, '1') and isinstance(speed, (int, float)) and not isinstance(speed, bool) and 0 < speed <= 1e9:
            links.append({'name': name, 'speed_mbps': speed})
    wireless = data['wireless']
    # airOS station mode only; AP status must not become a subscriber signal.
    strength = signal(wireless.get('signal')) if wireless.get('mode') in ('sta', 'station', 'Station', 'sta-wds', 'sta-ptmp', 'sta-ptp') else None
    return {'ethernet_links': links, 'signal_dbm': strength, 'telemetry_source': 'airOS API'}


async def airos(client, base, credentials):
    payload = {key: (None, value) for key, value in {
        'username': credentials['api_username'], 'password': credentials['api_password'],
        'uri': '/status.cgi', 'submit': 'Login'}.items()}
    status, raw = await request(client, 'POST', base + '/login.cgi', files=payload)
    if status not in (200, 302, 303):
        raise PermissionError('Device API login failed')
    status, raw = await request(client, 'GET', base + '/status.cgi')
    if status != 200:
        raise PermissionError('Device API status unavailable')
    return airos_values(json.loads(raw))


async def collect_api(address, credentials, vendor='generic', transport=None):
    host = '[' + address + ']' if ':' in address else address
    schemes = ['https', 'http'] if credentials.get('allow_http') else ['https']
    for scheme in schemes:
        base = scheme + '://' + host
        async with httpx.AsyncClient(timeout=httpx.Timeout(2, connect=1), follow_redirects=False,
                                     trust_env=False, verify=credentials.get('verify_tls', True), transport=transport) as client:
            try:
                status, root = await request(client, 'GET', base + '/')
                page = root.decode('utf-8', errors='ignore').lower()
                kind = vendor
                if kind == 'generic':
                    if 'mikrotik' in page or 'routeros' in page:
                        kind = 'mikrotik'
                    elif 'airos' in page or 'ubiquiti' in page or 'ubnt' in page:
                        kind = 'ubiquiti'
                # Authentication is sent only after a supported device is identified.
                if kind == 'mikrotik':
                    return await routeros(client, base, credentials)
                if kind == 'ubiquiti':
                    return await airos(client, base, credentials)
            except PermissionError:
                raise  # No repeated password attempts or downgrade after rejected login.
            except (httpx.HTTPError, ValueError, KeyError, TypeError):
                continue
    raise RuntimeError('No supported device API responded')
