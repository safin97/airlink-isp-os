"""Owner-controlled L2TP/IPsec client; only the reserved AirLink profile is managed.

Secrets travel over the root-only system D-Bus connection, never command arguments.
NetworkManager stores them in its root-readable system connection keyfile.
"""
import base64
import ipaddress
import re
import shutil
import sys
import threading
from pathlib import Path

NM = 'org.freedesktop.NetworkManager'
ROOT = '/org/freedesktop/NetworkManager'
PROFILE_UUID = '15ef8430-e9aa-4d99-936d-2a2605a3e62b'
PROFILE_NAME = 'AirLink owner L2TP'
SERVICE = NM + '.l2tp'
LOCK = threading.RLock()
FIELDS = {'server', 'username', 'password', 'psk', 'routes'}


def validate(data, saved_secrets=None):
    if not isinstance(data, dict) or set(data) - FIELDS:
        raise ValueError('Unknown VPN setting')
    result = {}
    for key, limit in [('server', 253), ('username', 128), ('password', 512), ('psk', 512)]:
        value = data.get(key, '')
        if not isinstance(value, str) or len(value) > limit or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError('Invalid VPN ' + key)
        result[key] = value.strip() if key in ('server', 'username') else value
    host = result['server']
    try:
        address = ipaddress.ip_address(host)
        valid = address.version == 4 and not (address.is_unspecified or address.is_multicast or address.is_loopback)
    except ValueError:
        valid = (not re.fullmatch(r'[0-9.]+', host) and bool(host) and all(
            re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?', label)
            for label in host.split('.')))
    if not valid:
        raise ValueError('Enter a VPN server IPv4 address or hostname, without a URL or port')
    if not result['username']:
        raise ValueError('Enter the VPN username')
    for field, secret in [('password', 'password'), ('psk', 'ipsec-psk')]:
        result[field] = result[field] or (saved_secrets or {}).get(secret, '')
        if not result[field]:
            raise ValueError('Enter the VPN password and IPsec shared key')
    routes = data.get('routes', [])
    if not isinstance(routes, list) or len(routes) > 32:
        raise ValueError('Provide at most 32 remote IPv4 subnets')
    result['routes'] = []
    for route in routes:
        try:
            if not isinstance(route, str) or '/' not in route:
                raise ValueError()
            network = ipaddress.ip_network(route, strict=True)
            if network.version != 4 or network.prefixlen == 0 or network.is_loopback or network.is_multicast or network.is_link_local:
                raise ValueError()
        except ValueError:
            raise ValueError('Use remote IPv4 subnets such as 192.168.88.0/24; a default route is not allowed') from None
        if str(network) not in result['routes']:
            result['routes'].append(str(network))
    return result


def supported():
    return sys.platform == 'linux' and shutil.which('nmcli') is not None and any(
        Path(path).is_file() for path in ('/usr/lib/NetworkManager/VPN/nm-l2tp-service.name',
                                         '/usr/lib/x86_64-linux-gnu/NetworkManager/VPN/nm-l2tp-service.name',
                                         '/usr/lib64/NetworkManager/VPN/nm-l2tp-service.name'))


class NetworkManager:
    def __init__(self):
        import dbus
        self.dbus = dbus
        self.bus = dbus.SystemBus(private=True)

    def close(self):
        self.bus.close()

    def interface(self, path, name):
        return self.dbus.Interface(self.bus.get_object(NM, path), name)

    def properties(self, path, name):
        return self.interface(path, 'org.freedesktop.DBus.Properties').GetAll(name, timeout=10)

    def profile(self):
        settings = self.interface(ROOT + '/Settings', NM + '.Settings')
        for path in settings.ListConnections(timeout=10):
            connection = self.interface(path, NM + '.Settings.Connection')
            data = connection.GetSettings(timeout=10)
            if str(data.get('connection', {}).get('uuid')) == PROFILE_UUID:
                if data['connection'].get('id') != PROFILE_NAME or data.get('vpn', {}).get('service-type') != SERVICE:
                    raise ValueError('The reserved AirLink VPN profile conflicts with another system connection')
                return str(path), data
        return None, {}

    def secrets(self, path):
        if path is None:
            return {}
        secrets = dict(self.interface(path, NM + '.Settings.Connection').GetSecrets('vpn', timeout=10).get('vpn', {}).get('secrets', {}))
        # The plugin treats a 0s prefix as base64. Expose literal input internally
        # so preserving a saved key cannot encode it a second time.
        psk = secrets.get('ipsec-psk', '')
        if psk.startswith('0s'):
            secrets['ipsec-psk'] = base64.b64decode(psk[2:], validate=True).decode('utf-8')
        return secrets

    def active(self):
        for path in self.properties(ROOT, NM).get('ActiveConnections', []):
            props = self.properties(path, NM + '.Connection.Active')
            if str(props.get('Uuid')) == PROFILE_UUID:
                state = int(self.properties(path, NM + '.VPN.Connection').get('VpnState', 0))
                addresses = []
                if props.get('Ip4Config', '/') != '/':
                    addresses = [str(a['address']) for a in self.properties(props['Ip4Config'], NM + '.IP4Config').get('AddressData', [])]
                return str(path), state, addresses
        return None, 7, []

    def save(self, path, value):
        d = self.dbus
        data = {'connection': {'id': PROFILE_NAME, 'uuid': PROFILE_UUID, 'type': 'vpn',
                               'autoconnect': False, 'permissions': d.Array(['user:root:'], signature='s')},
                'vpn': {'service-type': SERVICE,
                        'data': d.Dictionary({'gateway': value['server'], 'user': value['username'],
                            'user-auth-type': 'password', 'machine-auth-type': 'psk', 'ipsec-enabled': 'yes',
                            'password-flags': '0', 'ipsec-psk-flags': '0', 'ephemeral-port': 'yes'}, signature='ss'),
                        'secrets': d.Dictionary({'password': value['password'],
                            'ipsec-psk': '0s' + base64.b64encode(value['psk'].encode('utf-8')).decode('ascii')}, signature='ss')},
                'ipv4': {'method': 'auto', 'never-default': True, 'ignore-auto-dns': True,
                         'ignore-auto-routes': True, 'route-data': d.Array([
                             d.Dictionary({'dest': route.split('/')[0], 'prefix': d.UInt32(int(route.split('/')[1]))}, signature='sv')
                             for route in value['routes']], signature='a{sv}')},
                'ipv6': {'method': 'disabled'}}
        typed = d.Dictionary({key: d.Dictionary(value, signature='sv') for key, value in data.items()}, signature='sa{sv}')
        if path:
            self.interface(path, NM + '.Settings.Connection').Update(typed, timeout=10)
        else:
            self.interface(ROOT + '/Settings', NM + '.Settings').AddConnection(typed, timeout=10)

    def connect(self, path):
        self.interface(ROOT, NM).ActivateConnection(path, '/', '/', timeout=10)

    def disconnect(self, path):
        self.interface(ROOT, NM).DeactivateConnection(path, timeout=10)

    def delete(self, path):
        self.interface(path, NM + '.Settings.Connection').Delete(timeout=10)


def status(manager):
    path, profile = manager.profile()
    _, state, addresses = manager.active()
    data = profile.get('vpn', {}).get('data', {})
    secrets = manager.secrets(path)
    return {'supported': True, 'configured': bool(path),
            'status': ({1: 'connecting', 2: 'connecting', 3: 'connecting', 4: 'connecting',
                        5: 'connected', 6: 'failed', 7: 'disconnected'}.get(state, 'unknown') if path else 'not_configured'),
            'addresses': addresses, 'server': str(data.get('gateway', '')), 'username': str(data.get('user', '')),
            'has_password': bool(secrets.get('password')), 'has_psk': bool(secrets.get('ipsec-psk')),
            'routes': [str(r['dest']) + '/' + str(r['prefix']) for r in profile.get('ipv4', {}).get('route-data', [])]}


def action(name, data):
    if name not in {'status', 'save', 'connect', 'disconnect', 'delete'}:
        raise ValueError('Unknown VPN action')
    if name != 'save' and data:
        raise ValueError('This VPN action does not accept settings')
    if not supported():
        reason = 'L2TP/IPsec requires the installed AirLink Linux PC with NetworkManager L2TP and strongSwan support.'
        if name == 'status':
            return {'supported': False, 'configured': False, 'status': 'unavailable', 'reason': reason}
        raise ValueError(reason)
    with LOCK:
        manager = None
        try:
            manager = NetworkManager()
            if name != 'status':
                path, _ = manager.profile()
                active, state, _ = manager.active()
                busy = active and state not in (6, 7)
                if name == 'save':
                    if busy:
                        raise ValueError('Disconnect the VPN before editing its settings')
                    manager.save(path, validate(data, manager.secrets(path)))
                elif name == 'connect':
                    if path is None:
                        raise ValueError('Save VPN settings first')
                    if not busy:
                        manager.connect(path)
                elif name == 'disconnect':
                    if busy:
                        manager.disconnect(active)
                elif name == 'delete':
                    if busy:
                        raise ValueError('Disconnect the VPN before removing its settings')
                    if path:
                        manager.delete(path)
            return status(manager)
        except ValueError:
            raise
        except Exception:
            # D-Bus errors can include connection settings; never return their raw text.
            raise ValueError('VPN operation failed. Check the VPN service, server address, credentials and IPsec shared key.') from None
        finally:
            if manager is not None:
                manager.close()
