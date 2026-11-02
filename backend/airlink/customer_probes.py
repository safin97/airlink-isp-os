"""Bounded automatic probes of IPs obtained from the signed-in user's SAS4 list."""
import asyncio
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
import hashlib
import ipaddress
import json
import threading
import time
import sys
from sqlalchemy import select
from .models import CustomerProbeSettings, SNMPProfile
from .security import cipher
from .client_telemetry import number
from .device_api import collect_api, detect_vendor
from .vendor_identity import VENDOR_LABELS, merge_vendor

DEFAULTS = {'enabled': True, 'community': '', 'api_username': '', 'api_password': '',
            'verify_tls': True, 'allow_http': False, 'try_public_snmp': True}


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
    config['configured_snmp_count'] = len(candidates[:4])
    candidates = candidates[:4]
    if config['try_public_snmp']:
        candidates = [{'version': '2c', 'community': 'public'}] + [
            candidate for candidate in candidates if not (
                candidate.get('version') in ('1', '2c') and candidate.get('community') == 'public')]
    config['snmp_candidates'] = candidates
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


SNMP_BUDGET = 24
PROBE_BUDGET = 33


async def reachable(address):
    proc = None
    try:
        proc = await asyncio.create_subprocess_exec(
            'ping', '-n', '-c', '1', '-W', '1000' if sys.platform == 'darwin' else '1', address,
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        await asyncio.wait_for(proc.wait(), timeout=2)
        return proc.returncode == 0
    except asyncio.TimeoutError:
        return False
    except OSError:
        return None
    finally:
        if proc and proc.returncode is None:
            proc.kill()
            await proc.wait()


async def probe(address, config):
    result = {'ethernet_links': [], 'signal_dbm': None, 'telemetry_status': 'unreachable', 'telemetry_source': None}
    ping_task = asyncio.create_task(reachable(address))
    async def identity():
        try:
            return await asyncio.wait_for(detect_vendor(address, config), timeout=3)
        except Exception:
            return 'generic'
    identity_task = asyncio.create_task(identity())
    try:
        try:
            await asyncio.wait_for(_telemetry(address, config, result), timeout=PROBE_BUDGET)
        except asyncio.TimeoutError:
            pass  # Keep SNMP readings even when a later API request times out.
        web_vendor = await identity_task
        vendor = result.get('detected_vendor', 'generic')
        if vendor == 'generic' and web_vendor != 'generic':
            vendor = web_vendor
            result['vendor_detection_source'] = 'Device web interface'
        result['detected_vendor'] = vendor
        result['vendor_label'] = VENDOR_LABELS.get(vendor, 'Unknown / Generic')
        result['device_reachable'] = await ping_task
        if web_vendor != 'generic':
            result['device_reachable'] = True
        if result['telemetry_status'] == 'available':
            result['device_reachable'] = True
        elif result['device_reachable'] and result['telemetry_status'] == 'unreachable':
            result['telemetry_status'] = 'snmp_unavailable'
        return result
    finally:
        for task in (ping_task, identity_task):
            if not task.done():
                task.cancel()
        await asyncio.gather(ping_task, identity_task, return_exceptions=True)


def snmp_attempts(credentials_list):
    attempts = []
    for version in ('1', '2c', '3'):
        for credentials in credentials_list:
            saved_version = credentials.get('version', '3')
            if (version == '3') != (saved_version == '3'):
                continue
            if version == '3' and not all(credentials.get(key) for key in ('username', 'auth_key', 'priv_key')):
                continue
            if version != '3' and not credentials.get('community'):
                continue
            candidate = {**credentials, 'version': version}
            if candidate not in attempts:
                attempts.append(candidate)
    return attempts


async def _telemetry(address, config, result):
    from monitoring.snmp import collect
    vendor = 'generic'
    attempts = snmp_attempts(config['snmp_candidates'])
    deadline = time.monotonic() + SNMP_BUDGET
    for credentials in attempts:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        try:
            values = await asyncio.wait_for(collect(address, credentials, 0, vendor='auto', link_only=True), timeout=min(12, remaining))
            vendor = values.get('detected_vendor', 'generic')
            result.update(detected_vendor=vendor, vendor_detection_source='SNMP')
            source = ('MikroTik ' if vendor == 'mikrotik' else '') + 'SNMP v' + ('2' if credentials['version'] == '2c' else credentials['version'])
            result.update(readings(values), telemetry_status='available', telemetry_source=source)
            break
        except Exception:
            continue
    if config.get('api_username') and config.get('api_password') and (not result['ethernet_links'] or result['signal_dbm'] is None):
        try:
            api = await asyncio.wait_for(collect_api(address, config, vendor), timeout=8)
            result['detected_vendor'] = merge_vendor(vendor, api.get('detected_vendor'))
            if api.get('detected_vendor') not in (None, 'generic'):
                result['vendor_detection_source'] = 'API'
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
                return await asyncio.wait_for(probe(address, config), timeout=PROBE_BUDGET + 2)
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
                row.setdefault('telemetry_source', 'SNMP')
                row['device_reachable'] = True
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
                        if field in ('detected_vendor', 'vendor_label', 'vendor_detection_source') and row.get('detected_vendor') not in (None, 'generic') and cached[1].get('detected_vendor') in (None, 'generic'):
                            continue
                        if row.get('telemetry_status') == 'available' and cached[1]['telemetry_status'] != 'available' and field in ('telemetry_status', 'telemetry_source', 'device_reachable'):
                            continue
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
