"""Bounded read-only RouterOS REST and legacy airOS status adapters."""
import json
import math
import re
from urllib.parse import urljoin, urlsplit
import httpx
from .vendor_identity import identify_vendor
from .wireless_clients import public_clients, ssids, username_map, mac_address
from .device_telemetry import count_ethernet_ports

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


def numeric(value, low=0, high=1e18):
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
        return number if math.isfinite(number) and low <= number <= high else None
    except (TypeError, ValueError):
        return None


def uptime_seconds(value):
    direct = numeric(value)
    if direct is not None:
        return direct
    if not isinstance(value, str) or not re.fullmatch(r'(?:\d+w)?(?:\d+d)?(?:\d+h)?(?:\d+m)?(?:\d+(?:\.\d+)?s)?', value) or not value:
        return None
    return sum(float(amount) * {'w':604800, 'd':86400, 'h':3600, 'm':60, 's':1}[unit]
               for amount, unit in re.findall(r'(\d+(?:\.\d+)?)([wdhms])', value))


def resource_values(resource):
    if not isinstance(resource, dict):
        return {}
    values = {}
    for field, raw in (('cpu_percent', numeric(resource.get('cpu-load'), 0, 100)),
                       ('uptime_seconds', uptime_seconds(resource.get('uptime')))):
        if raw is not None:
            values[field] = raw
    total, free = numeric(resource.get('total-memory'), 1), numeric(resource.get('free-memory'))
    if total is not None and free is not None and free <= total:
        values.update(memory_total_bytes=total, memory_used_bytes=total-free, memory_percent=100*(total-free)/total)
    for source, target in (('version', 'firmware_version'), ('board-name', 'device_model')):
        if isinstance(resource.get(source), str):
            values[target] = resource[source][:120]
    return values


async def routeros(client, base, credentials, inventory=False, ppp_active=False):
    auth = httpx.BasicAuth(credentials['api_username'], credentials['api_password'])
    read_status = {}
    async def read(path, payload=None):
        status, raw = await request(client, 'GET' if payload is None else 'POST', base + '/rest/' + path,
                                    auth=auth, **({} if payload is None else {'json': payload}))
        read_status[path] = status
        if status in (401, 403):
            raise PermissionError('Device API credentials rejected')
        if status != 200:
            return None
        return json.loads(raw)
    interfaces = await read('interface/ethernet?.proplist=.id,name,running,disabled')
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
    wireless_values = {}
    registration_complete = True
    registered = {}
    registered_macs = set()
    largest_reported_count = 0
    for path, field in (() if ppp_active else (('interface/wireless/registration-table', 'signal-strength'),
                        ('interface/wifi/registration-table', 'signal'),
                        ('interface/wifiwave2/registration-table', 'signal'))):
        data = await read(path)
        if inventory and not isinstance(data, list):
            # A missing radio API is normal; a failed existing API is not an
            # empty registration table and cannot prove disconnection.
            registration_complete &= read_status.get(path) == 404
        if inventory and isinstance(data, list):
            largest_reported_count = max(largest_reported_count, len(data))
            registered_macs.update(mac for row in data if isinstance(row, dict)
                                   for mac in [mac_address(row.get('mac-address'))] if mac)
            radios = await read(path.rsplit('/', 1)[0] + '?.proplist=name,ssid,configuration.ssid')
            names = {str(row.get('name', '')): row.get('ssid') or row.get('configuration.ssid')
                     for row in radios if isinstance(row, dict)} if isinstance(radios, list) else {}
            wireless_values['wireless_ssids'] = ssids([*wireless_values.get('wireless_ssids', []), *names.values()])
            clients = public_clients([
                {'mac_address': row.get('mac-address'), 'interface': row.get('interface'),
                 'ssid': row.get('ssid') or names.get(str(row.get('interface', ''))),
                 'signal_dbm': signal(row.get(field))} for row in data[:256] if isinstance(row, dict)])
            wireless_values['wireless_registration_source'] = 'RouterOS API'
            registration_complete &= len(data) == len(clients)
            for row in clients:
                registered[row['mac_address']] = row
            # wifi/wifiwave2 may expose the same clients. Merge by MAC and keep
            # polling all radio families so a second radio is never ignored.
            wireless_values['wireless_clients'] = max(len(registered_macs), largest_reported_count)
            wireless_values['wireless_registrations'] = list(registered.values())[:256]
            signals = [row['signal_dbm'] for row in registered.values() if row['signal_dbm'] is not None]
            if signals:
                wireless_values['weakest_signal_dbm'] = min(signals)
            continue
        if isinstance(data, list) and data:
            # More than one station cannot be attributed to this customer's link.
            strength = signal(data[0].get(field)) if len(data) == 1 and isinstance(data[0], dict) else None
            signals = [signal(row.get(field)) for row in data[:256] if isinstance(row, dict)]
            signals = [value for value in signals if value is not None]
            wireless_values['wireless_clients'] = len(data)
            if signals:
                wireless_values['weakest_signal_dbm'] = min(signals)
            break
        if isinstance(data, list):
            wireless_values.setdefault('wireless_clients', 0)
    result = {'ethernet_links': links, 'signal_dbm': strength, 'telemetry_source': 'RouterOS API',
              'detected_vendor': 'mikrotik', 'vendor_detection_source': 'API'}
    if inventory:
        port_states = [
            {'type': 6, 'name': str(port.get('name', port.get('.id', '')))[:120],
             'admin_status': 2 if port.get('disabled') in (True, 'true') else 1,
             'status': (1 if port.get('running') in (True, 'true') else
                        2 if port.get('running') in (False, 'false') else None)}
            for port in interfaces if isinstance(port, dict)]
        speeds = {port['name']: port['speed_mbps'] for port in links}
        for port in port_states:
            if port['name'] in speeds:
                port['speed_mbps'] = speeds[port['name']]
        result['ethernet_port_states'] = port_states
        counts = count_ethernet_ports(port_states)
        if counts:
            result['ethernet_port_counts'] = counts
        if ppp_active:
            try:
                # Count sessions, including repeated usernames and non-PPPoE
                # services. Never query PPP secrets or infer zero on failure.
                active = await read('ppp/active?.proplist=.id')
                if isinstance(active, list) and all(
                        isinstance(row, dict) and isinstance(row.get('.id'), str) and row['.id']
                        for row in active):
                    result['ppp_active_count'] = len(active)
            except (PermissionError, httpx.HTTPError, ValueError, TypeError):
                pass  # Keep resource/link telemetry when PPP is inaccessible.
        if 'wireless_registrations' in wireless_values:
            wireless_values['wireless_registrations_complete'] = registration_complete and len(registered) <= 256
        result.update(wireless_values)
        if result.get('wireless_registrations'):
            try:
                active = await read('ppp/active?.proplist=name,caller-id,service')
                matches = username_map([
                    {'mac_address': row.get('caller-id'), 'username': row.get('name')}
                    for row in active if isinstance(row, dict) and row.get('service') == 'pppoe'
                ]) if isinstance(active, list) else {}
                for row in result['wireless_registrations']:
                    if row['mac_address'] in matches:
                        row['pppoe_username'] = matches[row['mac_address']]
                        if row['pppoe_username'] is None:
                            row['pppoe_username_status'] = 'ambiguous'
            except (PermissionError, httpx.HTTPError, ValueError, TypeError):
                pass  # Optional PPP read permission must not discard radio telemetry.
        resource = await read('system/resource')
        if isinstance(resource, list) and resource:
            resource = resource[0]
        result.update(resource_values(resource))
    return result


def airos_values(data, inventory=False):
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
    host = data.get('host') if isinstance(data.get('host'), dict) else {}
    identity = ' '.join(str(host.get(key, '')) for key in ('devmodel', 'model', 'fwversion'))
    result = {'ethernet_links': links, 'signal_dbm': strength, 'telemetry_source': 'airOS API',
              'detected_vendor': identify_vendor(description=identity, family='ubiquiti'),
              'vendor_detection_source': 'API'}
    if inventory:
        host = data.get('host') if isinstance(data.get('host'), dict) else {}
        port_states = [
            {'type': 6, 'name': port['ifname'], 'status': (1 if port['status'].get('plugged') in (1, True, '1') else
                                  2 if port['status'].get('plugged') in (0, False, '0') else None)}
            for port in ports if isinstance(port, dict)
            and isinstance(port.get('ifname'), str) and re.fullmatch(r'eth\d+', port['ifname'])
            and isinstance(port.get('status'), dict)]
        speeds = {port['name']: port['speed_mbps'] for port in links}
        for port in port_states:
            if port['name'] in speeds:
                port['speed_mbps'] = speeds[port['name']]
        result['ethernet_port_states'] = port_states
        counts = count_ethernet_ports(port_states)
        if counts:
            result['ethernet_port_counts'] = counts
        result['wireless_ssids'] = ssids([wireless.get('essid') or wireless.get('ssid')])
        stations = data.get('sta')
        if isinstance(stations, list):
            result['wireless_registrations'] = public_clients([
                {'mac_address': row.get('mac'), 'interface': row.get('ifname'),
                 'ssid': wireless.get('essid') or wireless.get('ssid'),
                 'signal_dbm': signal(row.get('signal'))} for row in stations[:256] if isinstance(row, dict)])
            result['wireless_registration_source'] = 'airOS API'
            result['wireless_registrations_complete'] = len(stations) == len(result['wireless_registrations'])
            result['wireless_clients'] = len(stations)
        for key, raw in (('cpu_percent', numeric(host.get('cpuload'), 0, 100)),
                         ('uptime_seconds', numeric(host.get('uptime'))),
                         ('wireless_clients', numeric(wireless.get('count'), 0, 100000))):
            if raw is not None:
                result[key] = raw
        total, free = numeric(host.get('totalram'), 1), numeric(host.get('freeram'))
        if total is not None and free is not None and free <= total:
            result.update(memory_total_bytes=total, memory_used_bytes=total-free, memory_percent=100*(total-free)/total)
        frequency = numeric(wireless.get('frequency'), 1, 65535)
        if frequency is not None:
            result['radio_frequencies_mhz'] = [frequency]
        for source, target in (('fwversion', 'firmware_version'), ('devmodel', 'device_model')):
            if isinstance(host.get(source), str):
                result[target] = host[source][:120]
    return result


async def airos(client, base, credentials, inventory=False):
    payload = {key: (None, value) for key, value in {
        'username': credentials['api_username'], 'password': credentials['api_password'],
        'uri': '/status.cgi', 'submit': 'Login'}.items()}
    status, raw = await request(client, 'POST', base + '/login.cgi', files=payload)
    if status not in (200, 302, 303):
        raise PermissionError('Device API login failed')
    status, raw = await request(client, 'GET', base + '/status.cgi')
    if status != 200:
        raise PermissionError('Device API status unavailable')
    return airos_values(json.loads(raw), inventory=inventory)


async def collect_api(address, credentials, vendor='generic', transport=None, inventory=False, timeout=None):
    ppp_active = vendor == 'mikrotik_ccr'
    if vendor in ('mikrotik_switch', 'mikrotik_ccr'):
        vendor = 'mikrotik'
    host = '[' + address + ']' if ':' in address else address
    schemes = [credentials['protocol']] if credentials.get('protocol') in ('http', 'https') else (['https', 'http'] if credentials.get('protocol') == 'both' or credentials.get('allow_http') else ['https'])
    for scheme in schemes:
        port = credentials.get('port')
        base = scheme + '://' + host + (':' + str(port) if port else '')
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout) if timeout is not None else httpx.Timeout(2, connect=1), follow_redirects=False,
                                     trust_env=False, verify=credentials.get('verify_tls', True), transport=transport) as client:
            try:
                status, root = await request(client, 'GET', base + '/')
                page = root.decode('utf-8', errors='ignore').lower()
                kind = 'ubiquiti' if vendor in ('ubiquiti_m5', 'ubiquiti_ac') else vendor
                if kind in ('generic', 'auto'):
                    if 'mikrotik' in page or 'routeros' in page:
                        kind = 'mikrotik'
                    elif 'airos' in page or 'ubiquiti' in page or 'ubnt' in page:
                        kind = 'ubiquiti'
                # Authentication is sent only after a supported device is identified.
                if kind == 'mikrotik':
                    return await routeros(client, base, credentials, inventory=inventory, ppp_active=ppp_active)
                if kind == 'ubiquiti':
                    return await airos(client, base, credentials, inventory=inventory)
            except PermissionError:
                raise  # No repeated password attempts or downgrade after rejected login.
            except (httpx.HTTPError, ValueError, KeyError, TypeError):
                continue
    raise RuntimeError('No supported device API responded')


async def detect_vendor(address, config, transport=None):
    """Read public device branding only; never send credentials or follow off-device redirects."""
    host = '[' + address + ']' if ':' in address else address
    schemes = ['https', 'http'] if config.get('allow_http') else ['https']
    for scheme in schemes:
        base = scheme + '://' + host + '/'
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(1, connect=.7), follow_redirects=False,
                    trust_env=False, verify=config.get('verify_tls', True), transport=transport) as client:
                async def public_page(url):
                    async with client.stream('GET', url) as response:
                        content = bytearray()
                        async for chunk in response.aiter_bytes():
                            content.extend(chunk)
                            if len(content) > MAX_RESPONSE:
                                raise ValueError('Device response too large')
                        return response.status_code, response.headers, content.decode('utf-8', errors='ignore')
                status, headers, page = await public_page(base)
                # Login redirects on the same device are common on airOS/Mimosa.
                if status in (301, 302, 303, 307, 308):
                    target = urljoin(base, headers.get('location', ''))
                    if urlsplit(target).netloc != urlsplit(base).netloc or urlsplit(target).scheme != scheme:
                        continue
                    status, headers, page = await public_page(target)
                if status not in (200, 401, 403):
                    continue
                # Older routers advertise their brand in a public Basic/Digest
                # realm even when the login page itself requires authentication.
                branding = (headers.get('www-authenticate', '')[:512] + '\n'
                            + headers.get('server', '')[:256] + '\n' + page[:2048])
                vendor = identify_vendor(description=branding)
                if vendor != 'generic':
                    return vendor
        except (httpx.HTTPError, ValueError):
            continue
    return 'generic'
