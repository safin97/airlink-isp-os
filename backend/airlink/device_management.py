"""Explicit wireless configuration changes using the RouterOS REST API."""
import asyncio
import json
import re
import httpx
from .device_api import request

MENUS = ('wireless', 'wifi', 'wifiwave2')


class ManagementError(Exception):
    def __init__(self, message, status=502):
        super().__init__(message)
        self.status = status


class ReadUnavailable(ManagementError):
    pass


def require_credentials(config):
    if not config.get('enabled') or not config.get('api_username') or not config.get('api_password'):
        raise ManagementError('Set device API credentials in Edit Tower first.', 409)


async def wireless(address, config, change=None, transport=None):
    require_credentials(config)
    protocols = ['https', 'http'] if config.get('protocol') == 'both' else [config['protocol']]
    for index, protocol in enumerate(protocols):
        try:
            return await wireless_once(address, {**config, 'protocol': protocol}, change, transport)
        except (httpx.HTTPError, ReadUnavailable):
            if index == len(protocols) - 1:
                raise
    raise ManagementError('Device API is unreachable.')


async def wireless_once(address, config, change=None, transport=None):
    host = '[' + address + ']' if ':' in address else address
    base = config['protocol'] + '://' + host + (':' + str(config['port']) if config.get('port') else '')
    auth = httpx.BasicAuth(config['api_username'], config['api_password'])
    async with httpx.AsyncClient(timeout=httpx.Timeout(3, connect=1), follow_redirects=False,
            trust_env=False, verify=config.get('verify_tls', True), transport=transport) as client:
        radios = []
        supported_menu = False
        for menu in MENUS:
            if change and menu != change['menu']:
                continue
            status, raw = await request(client, 'GET', base + '/rest/interface/' + menu,
                auth=auth, params={'.proplist': '.id,name,ssid,configuration.ssid,disabled,dynamic,configuration.manager'})
            if status in (401, 403):
                raise ManagementError('Device API login or read permission was rejected.', 403)
            if status in (400, 404):
                continue  # RouterOS installations expose different wireless packages.
            if status != 200:
                raise ReadUnavailable('Device wireless settings could not be read.')
            try:
                rows = json.loads(raw)
            except (ValueError, TypeError):
                raise ReadUnavailable('Invalid device wireless response.') from None
            if not isinstance(rows, list):
                raise ReadUnavailable('Invalid device wireless response.')
            supported_menu = True
            for row in rows[:32]:
                if not isinstance(row, dict) or not re.fullmatch(r'\*[0-9A-Fa-f]+', str(row.get('.id', ''))):
                    continue
                ssid = row.get('ssid') if menu == 'wireless' else row.get('configuration.ssid')
                local = row.get('configuration.manager', 'local') == 'local' and row.get('dynamic') not in ('true', True)
                radios.append({'menu': menu, 'id': row['.id'], 'name': str(row.get('name', row['.id']))[:120],
                    'ssid': ssid if isinstance(ssid, str) else None,
                    'editable': local and isinstance(ssid, str),
                    'reason': None if local and isinstance(ssid, str) else 'SSID is inherited or managed by a controller.'})
        if not supported_menu:
            raise ReadUnavailable('No supported wireless API responded.')
        if change is None:
            return radios
        radio = next((r for r in radios if r['menu'] == change['menu'] and r['id'] == change['radio_id']), None)
        if radio is None:
            raise ManagementError('Wireless interface changed. Reload its settings.', 409)
        if not radio['editable']:
            raise ManagementError('This wireless interface must be changed in its controller or profile.', 409)
        if radio['ssid'] != change['previous_ssid']:
            raise ManagementError('SSID changed since you opened it. Reload before saving.', 409)
        if radio['ssid'] == change['ssid']:
            return {'status': 'unchanged'}
        field = 'ssid' if change['menu'] == 'wireless' else 'configuration.ssid'
        # Exactly one write, only to the selected interface; no password or other config is returned.
        try:
            status, _ = await request(client, 'PATCH', base + '/rest/interface/' + change['menu'] + '/' + radio['id'],
                auth=auth, json={field: change['ssid']})
        except (httpx.HTTPError, ValueError):
            raise ManagementError('Change result is unknown. Reconnect and reload settings before retrying.', 504) from None
        if status in (401, 403):
            raise ManagementError('Device API write permission was rejected.', 403)
        if status not in (200, 204):
            raise ManagementError('Device did not accept the SSID change.')
        return {'status': 'accepted'}


def run(address, config, change=None):
    async def bounded():
        return await asyncio.wait_for(wireless(address, config, change), timeout=15)
    try:
        return asyncio.run(bounded())
    except ManagementError:
        raise
    except (httpx.HTTPError, ValueError, asyncio.TimeoutError):
        message = ('Change result is unknown. Reconnect and reload settings before retrying.' if change
                   else 'Device API is unreachable. Check the tower API connection settings.')
        raise ManagementError(message, 504) from None
