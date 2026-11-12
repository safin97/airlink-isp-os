"""Bounded automatic probes of IPs obtained from the signed-in user's SAS4 list."""
import asyncio
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
import hashlib
import ipaddress
import json
import threading
import time
from .models import CustomerProbeSettings, SAS4UserConnection, User, now
from .security import cipher
from .vendor_identity import VENDOR_LABELS

DEFAULTS = {'enabled': True, 'community': '', 'api_username': '', 'api_password': '',
            'verify_tls': True, 'allow_http': True, 'try_public_snmp': False}


def configuration(db, user):
    obj = db.get(CustomerProbeSettings, user.id)
    # Managers use the owner's monitoring settings only on the server; their
    # SAS4 customer scope and telemetry cache remain isolated.
    if obj is None and user.role == 'manager':
        obj = (db.query(CustomerProbeSettings).join(User, User.id == CustomerProbeSettings.user_id)
               .filter(User.role == 'owner', User.active.is_(True))
               .order_by(User.created_at, User.id).first())
    config = {**DEFAULTS, **(json.loads(cipher().decrypt(obj.encrypted_settings.encode())) if obj else {})}
    communities = []
    if isinstance(config.get('community'), str) and config['community'].strip():
        communities.append(config['community'].strip())
    if config.get('try_public_snmp') and 'public' not in communities:
        communities.append('public')
    # Try both community protocol versions without duplicating or returning secrets.
    config['snmp_candidates'] = [
        {'version': version, 'community': community}
        for community in communities for version in ('2c', '1')
    ]
    config['configured_snmp_count'] = len(communities)
    return config


def valid_address(value):
    if not isinstance(value, str):
        return None
    try:
        ip = ipaddress.ip_address(value)
        if (ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_unspecified
                or ip.is_reserved or getattr(ip, 'ipv4_mapped', None) or '%' in str(value)):
            return None
        return str(ip)
    except (ValueError, TypeError):
        return None


PROBE_BUDGET = 55


async def probe(address, config):
    from .online_device_auto import detect_and_connect
    from .device_management import ManagementError
    from .client_telemetry import snmp_readings
    from monitoring import snmp
    result = {'ethernet_links': [], 'signal_dbm': None, 'ssid': None,
              'telemetry_status': 'credentials_required', 'telemetry_source': None,
              'detected_vendor': 'generic', 'vendor_label': 'Unknown / Generic'}
    if not valid_address(address):
        result['telemetry_status'] = 'invalid_address'
        return result
    candidates = config.get('snmp_candidates', [])
    has_api = bool(config.get('api_username') and config.get('api_password'))
    if not candidates and not has_api:
        return result
    for credentials in candidates:
        try:
            values = await asyncio.wait_for(
                snmp.collect(address, credentials, 0, vendor='auto', link_only=True), 12)
            readings = snmp_readings(values)
            vendor = values.get('detected_vendor', 'generic')
            return {**result, **readings, 'telemetry_status': 'available',
                    'telemetry_source': 'SNMP v' + ('2' if credentials['version'] == '2c' else '1'),
                    'snmp_version': credentials['version'], 'detected_vendor': vendor,
                    'vendor_label': VENDOR_LABELS.get(vendor, 'Unknown / Generic'),
                    'vendor_detection_source': 'SNMP', 'device_reachable': True}
        except Exception:
            continue
    if not has_api:
        result['telemetry_status'] = 'snmp_unavailable'
        return result
    try:
        data = await asyncio.wait_for(detect_and_connect(address, {
            **config, 'transport': 'auto', 'protocol': 'both' if config.get('allow_http') else 'https',
            'telemetry_only': True, 'background': True}), PROBE_BUDGET)
        links = [{'name': p['name'], 'speed_mbps': p['speed_mbps']} for p in data.get('ethernet', [])
                 if p.get('speed_mbps') and p.get('status') == 'link-ok']
        primary = [p for p in links if p['name'].casefold() == 'ether1']
        wireless = data.get('wireless', [])
        signals = [r['signal_dbm'] for r in wireless if r.get('signal_dbm') is not None]
        ssids = {r['ssid'] for r in wireless if r.get('ssid')}
        vendor = data.get('detected_vendor', 'generic')
        connection = data.get('connection', {})
        source = {'routeros': 'RouterOS API', 'routeros_tls': 'RouterOS API-SSL', 'airos_ssh': 'Ubiquiti SSH'}.get(
            connection.get('transport'), data.get('vendor', 'Device') + ' ' + connection.get('protocol', 'https').upper())
        result.update(ethernet_links=primary or links, signal_dbm=signals[0] if len(signals) == 1 else None,
                      ssid=next(iter(ssids)) if len(ssids) == 1 else None, telemetry_status='available',
                      telemetry_source=source, detected_vendor=vendor, vendor_label=VENDOR_LABELS.get(vendor, 'Unknown / Generic'),
                      vendor_detection_source='API', device_reachable=True)
    except PermissionError:
        result['telemetry_status'] = 'authentication_failed'
    except (ManagementError, OSError, ValueError, RuntimeError, asyncio.TimeoutError):
        result['telemetry_status'] = 'api_unavailable'
    return result


class ProbeService:
    def __init__(self):
        self.lock = threading.RLock()
        self.pool = None
        self.cache = OrderedDict()
        self.pending = set()

    def start(self):
        with self.lock:
            if self.pool is None:
                self.pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix='customer-probe')

    def stop(self):
        with self.lock:
            if self.pool:
                self.pool.shutdown(wait=False, cancel_futures=True)
            self.pool = None
            self.cache.clear()

    def run(self, key, address, config):
        try:
            async def bounded():
                return await asyncio.wait_for(probe(address, config), timeout=PROBE_BUDGET + 2)
            try:
                result = asyncio.run(bounded())
            except Exception:
                result = {'ethernet_links': [], 'signal_dbm': None, 'ssid': None, 'telemetry_status': 'api_unavailable', 'telemetry_source': None}
            with self.lock:
                if self.pool is not None:
                    previous = self.cache.get(key)
                    stale_fields = []
                    if previous:
                        for field in ('ethernet_links', 'signal_dbm', 'ssid'):
                            if not result.get(field) and previous[1].get(field):
                                result[field] = previous[1][field]
                                stale_fields.append(field)
                    result['telemetry_stale_fields'] = stale_fields
                    result['telemetry_collected_at'] = now().isoformat()
                    self.cache[key] = (time.monotonic(), result)
                    self.cache.move_to_end(key)
                    while len(self.cache) > 10000:
                        self.cache.popitem(last=False)
        finally:
            with self.lock:
                self.pending.discard(key)

    def enrich(self, db, user, result, *, schedule=True):
        config = configuration(db, user)
        connection = db.get(SAS4UserConnection, user.id) if db is not None else None
        scope = (connection.username + '\0' + connection.encrypted_password) if connection else ''
        fingerprint = hashlib.sha256((json.dumps(config, sort_keys=True) + scope).encode()).hexdigest()
        for row in result.get('clients', []):
            # Online users never inherit inventory/SNMP readings or source labels.
            row.update(ethernet_links=[], signal_dbm=None, ssid=None, telemetry_source=None,
                       detected_vendor='generic', vendor_label='Unknown / Generic', telemetry_refreshing=False,
                       telemetry_status='disabled' if not config['enabled'] else 'credentials_required')
            if not config['enabled']:
                continue
            address = valid_address(row.get('ip_address'))
            if not address:
                row['telemetry_status'] = 'invalid_address'
                continue
            if not config.get('snmp_candidates') and not (
                    config.get('api_username') and config.get('api_password')):
                row['telemetry_status'] = 'credentials_required'
                continue
            key = (user.id, address, str(row.get('session_id')), str(row.get('username')), fingerprint)
            with self.lock:
                cached = self.cache.get(key)
                fresh = cached and time.monotonic() - cached[0] < (30 if cached[1]['telemetry_status'] == 'available' else 120)
                if cached:
                    for field, value in cached[1].items():
                        row[field] = value
                if not fresh:
                    row['telemetry_refreshing'] = bool(cached)
                    if not cached:
                        row['telemetry_status'] = 'pending'
                    if schedule and self.pool is not None and key not in self.pending and len(self.pending) < 128:
                        self.pending.add(key)
                        self.pool.submit(self.run, key, address, config)
                    if key in self.pending:
                        row['telemetry_status'] = 'connecting'
                        row['telemetry_refreshing'] = True
        return result


service = ProbeService()
