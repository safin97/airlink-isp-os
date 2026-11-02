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
from .client_telemetry import snmp_readings as readings
from .vendor_identity import VENDOR_LABELS

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
    result = {'ethernet_links': [], 'signal_dbm': None, 'ssid': None, 'telemetry_status': 'unreachable', 'telemetry_source': None}
    ping_task = asyncio.create_task(reachable(address))
    try:
        try:
            await asyncio.wait_for(_telemetry(address, config, result), timeout=PROBE_BUDGET)
        except asyncio.TimeoutError:
            pass  # Preserve any readings received before the deadline.
        vendor = result.get('detected_vendor', 'generic')
        result['detected_vendor'] = vendor
        result['vendor_label'] = VENDOR_LABELS.get(vendor, 'Unknown / Generic')
        result['device_reachable'] = await ping_task
        if result['telemetry_status'] == 'available':
            result['device_reachable'] = True
        elif result['device_reachable'] and result['telemetry_status'] == 'unreachable':
            result['telemetry_status'] = 'snmp_unavailable'
        return result
    finally:
        if not ping_task.done():
            ping_task.cancel()
        await asyncio.gather(ping_task, return_exceptions=True)


def snmp_attempts(credentials_list):
    attempts = []
    for version in ('1', '2c', '3'):
        for credentials in credentials_list:
            saved_version = credentials.get('version', '3')
            if saved_version == '2':
                saved_version = '2c'
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
            sample = readings(values)
            for field, value in sample.items():
                if value is not None and value != []:
                    result[field] = value
            result.update(telemetry_status='available', telemetry_source=source)
            # A v1 response with missing fields must not prevent a v2 attempt.
            if credentials['version'] != '1' or all(result.get(field) for field in ('ethernet_links', 'signal_dbm', 'ssid')):
                break
        except Exception:
            continue
    if not attempts:
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
                result = {'ethernet_links': [], 'signal_dbm': None, 'ssid': None, 'telemetry_status': 'unreachable', 'telemetry_source': None}
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
            if row.get('ethernet_links') and row.get('signal_dbm') is not None and row.get('ssid'):
                row.setdefault('telemetry_source', 'SNMP')
                row['device_reachable'] = True
                continue
            address = valid_address(row.get('ip_address'))
            if not address:
                row['telemetry_status'] = 'invalid_address'
                continue
            if not config['snmp_candidates']:
                row['telemetry_status'] = 'credentials_required'
                continue
            key = (user.id, address, str(row.get('session_id')), str(row.get('username')), fingerprint)
            with self.lock:
                cached = self.cache.get(key)
                fresh = cached and time.monotonic() - cached[0] < (30 if cached[1]['telemetry_status'] == 'available' else 120)
                if cached:
                    for field, value in cached[1].items():
                        if field in ('detected_vendor', 'vendor_label', 'vendor_detection_source') and row.get('detected_vendor') not in (None, 'generic') and cached[1].get('detected_vendor') in (None, 'generic'):
                            continue
                        if row.get('telemetry_status') == 'available' and cached[1]['telemetry_status'] != 'available' and field in ('telemetry_status', 'telemetry_source', 'device_reachable'):
                            continue
                        if field in ('ethernet_links', 'signal_dbm', 'ssid') and (row.get(field) or value is None or value == []):
                            continue
                        row[field] = value
                if not fresh:
                    if self.pool is not None and key not in self.pending and len(self.pending) < 128:
                        self.pending.add(key)
                        self.pool.submit(self.run, key, address, config)
                    if key in self.pending:
                        row['telemetry_status'] = 'checking'
                        row['telemetry_refreshing'] = True
        return result


service = ProbeService()
