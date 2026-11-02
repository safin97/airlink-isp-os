"""Bounded automatic probes of IPs obtained from the signed-in user's SAS4 list."""
import asyncio
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
import hashlib
import ipaddress
import json
import threading
import time
from sqlalchemy import select
from .models import CustomerProbeSettings, SNMPProfile
from .security import cipher
from .client_telemetry import number
from .device_api import collect_api

DEFAULTS = {'enabled': True, 'community': '', 'api_username': '', 'api_password': '',
            'verify_tls': True, 'allow_http': False}


def configuration(db, user):
    obj = db.get(CustomerProbeSettings, user.id)
    config = {**DEFAULTS, **(json.loads(cipher().decrypt(obj.encrypted_settings.encode())) if obj else {})}
    candidates = []
    if config['community']:
        candidates.append({'version': '2c', 'community': config['community']})
    # Only the owner can reuse global inventory credentials. Managers supply
    # their own customer credentials; SAS4 visibility grants no profile access.
    if user.role == 'owner':
        for profile in db.scalars(select(SNMPProfile).order_by(SNMPProfile.name).limit(4)):
            try:
                credentials = json.loads(cipher().decrypt(profile.encrypted_credentials.encode()))
                if credentials not in candidates:
                    candidates.append(credentials)
            except Exception:
                continue
    config['snmp_candidates'] = candidates[:4]
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


def readings(values):
    links = []
    for index, port in values.get('interfaces', {}).items():
        speed = port.get('speed_mbps')
        if port.get('type') == 6 and port.get('status') == 1 and number(speed, .001, 1e9):
            links.append({'name': str(port.get('name', index))[:120], 'speed_mbps': speed})
    signals = values.get('wireless', {}).get('signal_dbm', {})
    strength = next(iter(signals.values())) if len(signals) == 1 else None
    return {'ethernet_links': links, 'signal_dbm': strength if number(strength, -150, -.001) else None}


async def probe(address, config):
    from monitoring.snmp import collect
    result = {'ethernet_links': [], 'signal_dbm': None, 'telemetry_status': 'unreachable', 'telemetry_source': None}
    vendor = 'generic'
    attempts = []
    for credentials in config['snmp_candidates']:
        versions = ('2c', '1') if credentials.get('version', '3') in ('1', '2c') else ('3',)
        for version in versions:
            candidate = {**credentials, 'version': version}
            if candidate not in attempts:
                attempts.append(candidate)
    for credentials in attempts:
        try:
            values = await asyncio.wait_for(collect(address, credentials, 0, vendor='auto'), timeout=7)
            result.update(readings(values), telemetry_status='available', telemetry_source='SNMP v' + credentials['version'])
            vendor = values.get('detected_vendor', 'generic')
            break
        except Exception:
            continue
    if config.get('api_username') and config.get('api_password') and (not result['ethernet_links'] or result['signal_dbm'] is None):
        try:
            api = await asyncio.wait_for(collect_api(address, config, vendor), timeout=8)
            used = False
            for key in ('ethernet_links', 'signal_dbm'):
                if not result[key] and api.get(key) is not None and api.get(key) != []:
                    result[key] = api[key]
                    used = True
            if used or result['telemetry_status'] != 'available':
                source = result['telemetry_source']
                result['telemetry_source'] = (source + ' + ' if source else '') + api['telemetry_source']
            result['telemetry_status'] = 'available'
        except PermissionError:
            if result['telemetry_status'] != 'available': result['telemetry_status'] = 'authentication_failed'
        except Exception:
            pass
    elif not attempts:
        result['telemetry_status'] = 'credentials_required'
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
                return await asyncio.wait_for(probe(address, config), timeout=25)
            try:
                result = asyncio.run(bounded())
            except Exception:
                result = {'ethernet_links': [], 'signal_dbm': None, 'telemetry_status': 'unreachable', 'telemetry_source': None}
            with self.lock:
                if self.pool is not None:
                    self.cache[key] = (time.monotonic(), result)
                    self.cache.move_to_end(key)
                    while len(self.cache) > 2048:
                        self.cache.popitem(last=False)
        finally:
            with self.lock:
                self.pending.discard(key)

    def enrich(self, db, user, result):
        config = configuration(db, user)
        if not config['enabled']:
            return result
        fingerprint = hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest()
        for row in result.get('clients', []):
            # Fresh inventory data can still supply either field, but is not required.
            if row.get('ethernet_links') and row.get('signal_dbm') is not None:
                row['telemetry_source'] = 'SNMP'
                continue
            address = valid_address(row.get('ip_address'))
            if not address:
                row['telemetry_status'] = 'invalid_address'
                continue
            if not config['snmp_candidates'] and not (config['api_username'] and config['api_password']):
                row['telemetry_status'] = 'credentials_required'
                continue
            key = (user.id, address, str(row.get('session_id')), str(row.get('username')), fingerprint)
            with self.lock:
                cached = self.cache.get(key)
                if cached and time.monotonic() - cached[0] < (30 if cached[1]['telemetry_status'] == 'available' else 120):
                    for field, value in cached[1].items():
                        if field in ('ethernet_links', 'signal_dbm') and (value is None or value == []):
                            continue
                        row[field] = value
                else:
                    row['telemetry_status'] = 'checking'
                    if self.pool is not None and key not in self.pending and len(self.pending) < 128:
                        self.pending.add(key)
                        self.pool.submit(self.run, key, address, config)
        return result


service = ProbeService()
