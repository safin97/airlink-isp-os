"""Read-only Deye Cloud OpenAPI adapter; credentials and tokens stay server-side."""
import hashlib
import json
import math
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional
import httpx
from cryptography.fernet import InvalidToken
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator
from .db import get_db
from .models import DeyeConnection, DeyeGridHistory, now, audit
from .security import current_user, cipher, aware
from . import section_access

router = APIRouter(prefix='/api/integrations/deye', tags=['Deye Cloud'])
REGIONS = {'eu': 'https://eu1-developer.deyecloud.com',
           'am': 'https://us1-developer.deyecloud.com',
           'india': 'https://india-developer.deyecloud.com'}
LOCKS = [threading.RLock() for _ in range(64)]
CACHE_SECONDS = 5
ERROR_CACHE_SECONDS = 30
STATION_CACHE_SECONDS = 180
PATHS = {'/account/token', '/station/list', '/station/latest', '/station/device', '/device/latest'}


class ConnectionInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    region: Literal['eu', 'am', 'india'] = 'eu'
    login_type: Literal['email', 'username', 'mobile'] = 'email'
    account: str = Field(min_length=1, max_length=254)
    country_code: str = Field(default='', max_length=5, pattern=r'^[0-9]*$')
    app_id: str = Field(min_length=1, max_length=128, pattern=r'^[A-Za-z0-9_-]+$')
    app_secret: Optional[SecretStr] = Field(default=None, max_length=1024)
    password: Optional[SecretStr] = Field(default=None, max_length=1024)
    company_id: Optional[int] = Field(default=None, ge=1)

    @model_validator(mode='after')
    def validate_account(self):
        self.account = self.account.strip()
        if not self.account or (self.login_type == 'email' and '@' not in self.account):
            raise ValueError('Enter the Deye Cloud account login')
        if self.login_type == 'mobile' and (not self.account.isdigit() or not self.country_code):
            raise ValueError('Enter a mobile number and country code')
        return self


class DashboardStationInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    station_id: Optional[str] = Field(default=None, pattern=r'^[1-9][0-9]{0,18}$')
    page: int = Field(default=1, ge=1, le=1000)


def access(user=Depends(current_user), db=Depends(get_db)):
    if user.role != 'owner' and 'deye' not in section_access.effective(user, db):
        raise HTTPException(403, 'Deye Cloud access must be enabled by the owner')
    return user


def lock_for(user):
    return LOCKS[int(hashlib.sha256(user.id.encode()).hexdigest(), 16) % len(LOCKS)]


def encrypt(data):
    return cipher().encrypt(json.dumps(data).encode()).decode()


def decrypt(value):
    try:
        return json.loads(cipher().decrypt(value.encode()))
    except (InvalidToken, ValueError, TypeError):
        raise HTTPException(409, 'Reconnect Deye Cloud; saved credentials could not be opened.') from None


def request(region, path, body, token=None, app_id=None, transport=None):
    if path not in PATHS:
        raise ValueError('Unsupported Deye operation')
    try:
        with httpx.Client(timeout=httpx.Timeout(20, connect=5), follow_redirects=False,
                          trust_env=False, transport=transport) as client:
            with client.stream('POST', REGIONS[region] + '/v1.0' + path, json=body,
                               params={'appId': app_id} if app_id else None,
                               headers={'Authorization': 'Bearer ' + token} if token else {}) as response:
                if response.status_code in (401, 403):
                    raise HTTPException(502, 'Deye Cloud rejected access. Check the region, account and developer app permissions.')
                if response.status_code == 429:
                    raise HTTPException(502, 'Deye Cloud rate limit reached. Wait before refreshing again.')
                if response.status_code != 200:
                    raise HTTPException(502, 'Deye Cloud is unavailable. Try again later.')
                raw = bytearray()
                for chunk in response.iter_bytes():
                    raw.extend(chunk)
                    if len(raw) > 2 * 1024 * 1024:
                        raise HTTPException(502, 'Deye Cloud returned too much data.')
                result = json.loads(raw)
    except (httpx.HTTPError, ValueError):
        raise HTTPException(502, 'Could not read Deye Cloud. Check internet access and the selected region.') from None
    if not isinstance(result, dict) or result.get('success') is not True:
        raise HTTPException(502, 'Deye Cloud rejected the request. Check the login, App ID, App Secret and monitoring permissions.')
    return result


def login(region, credentials):
    body = {'appSecret': credentials['app_secret'], 'password': credentials['password_hash'],
            credentials['login_type']: credentials['account']}
    if credentials['login_type'] == 'mobile':
        body['countryCode'] = credentials['country_code']
    if credentials.get('company_id'):
        body['companyId'] = credentials['company_id']
    result = request(region, '/account/token', body, app_id=credentials['app_id'])
    token = result.get('accessToken')
    if not isinstance(token, str) or not token or len(token) > 32768:
        raise HTTPException(502, 'Deye Cloud did not return an access token.')
    try:
        lifetime = min(86400, max(60, int(result.get('expiresIn', 3600))))
    except (ValueError, TypeError):
        lifetime = 3600
    return token, now() + timedelta(seconds=lifetime - 30)


def public(row):
    if row is None:
        return {'configured': False}
    credentials = decrypt(row.encrypted_credentials)
    return {'configured': True, 'region': row.region, 'has_password': True, 'has_app_secret': True,
            'dashboard_station': row.dashboard_station,
            **{key: credentials.get(key) for key in ('login_type', 'account', 'country_code', 'app_id', 'company_id')}}


def connection(db, user):
    db.expire_all()
    row = db.get(DeyeConnection, user.id)
    if row is None:
        raise HTTPException(409, 'Connect your Deye Cloud account first.')
    return row


def cloud(row, path, body):
    if aware(row.token_expires) <= now():
        token, row.token_expires = login(row.region, decrypt(row.encrypted_credentials))
        row.encrypted_token = encrypt(token)
    return request(row.region, path, body, token=decrypt(row.encrypted_token))


def number(value, *, percentage=False, nonnegative=False):
    if isinstance(value, bool) or value is None:
        return None
    try:
        result = float(value)
    except (ValueError, TypeError):
        return None
    if not math.isfinite(result) or (percentage and not 0 <= result <= 100) or (nonnegative and result < 0):
        return None
    return result


def observation(value):
    try:
        if isinstance(value, (int, float)) or (isinstance(value, str) and value.replace('.', '', 1).isdigit()):
            stamp = float(value)
            return datetime.fromtimestamp(stamp / 1000 if stamp > 10**11 else stamp, timezone.utc)
        stamp = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return stamp.astimezone(timezone.utc) if stamp.tzinfo else None
    except (ValueError, TypeError, OSError, OverflowError):
        return None


def normalized(result):
    stamp = observation(result.get('lastUpdateTime'))
    age = (now() - stamp).total_seconds() if stamp else None
    values = {key: number(result.get(field), nonnegative=key not in {'battery_w', 'grid_w'}) for key, field in {
        'solar_w': 'generationPower', 'load_w': 'consumptionPower', 'battery_w': 'batteryPower',
        'grid_w': 'gridPower', 'charge_w': 'chargePower', 'discharge_w': 'dischargePower',
        'import_w': 'purchasePower', 'export_w': 'wirePower'}.items()}
    # Some stations use wirePower for signed grid exchange. Without the paired
    # purchase field, labeling it as export would be misleading.
    if values['import_w'] is None:
        values['export_w'] = None
    return {**values, 'battery_soc': number(result.get('batterySOC'), percentage=True),
            'observed_at': stamp.isoformat() if stamp else None,
            'freshness': 'unknown' if age is None or age < -60 else 'stale' if age > 900 else 'recent',
            'fetched_at': now().isoformat(), 'power_sources': result.get('power_sources', {})}


def station_list(result):
    rows = result.get('stationList')
    if not isinstance(rows, list) or len(rows) > 200:
        raise HTTPException(502, 'Deye Cloud returned an invalid station list.')
    stations = []
    for row in rows:
        if not isinstance(row, dict) or not str(row.get('id', '')).isdigit():
            raise HTTPException(502, 'Deye Cloud returned an invalid station.')
        stations.append({'id': str(row['id']), 'name': str(row.get('name') or 'Deye station')[:200],
                         'connection_status': str(row.get('connectionStatus') or 'Unknown')[:60]})
    total = result.get('total', len(stations))
    return {'stations': stations, 'total': total if isinstance(total, int) and total >= 0 else len(stations)}


@router.get('')
def settings(user=Depends(access), db=Depends(get_db)):
    with lock_for(user):
        return public(db.get(DeyeConnection, user.id))


@router.put('')
def save(data: ConnectionInput, user=Depends(access), db=Depends(get_db)):
    section_access.require_any(user, ('deye',), db, write=True)
    with lock_for(user):
        row = db.get(DeyeConnection, user.id)
        old = decrypt(row.encrypted_credentials) if row else {}
        credentials = data.model_dump(exclude={'password', 'app_secret', 'region'})
        changed = not row or row.region != data.region or any(credentials[k] != old.get(k) for k in credentials)
        password = data.password.get_secret_value() if data.password else ''
        secret = data.app_secret.get_secret_value() if data.app_secret else ''
        if changed and (not password or not secret):
            raise HTTPException(422, 'Enter the password and App Secret when connecting or changing the account.')
        credentials.update(password_hash=hashlib.sha256(password.encode()).hexdigest() if password else old['password_hash'],
                           app_secret=secret or old['app_secret'])
        token, expires = login(data.region, credentials)
        listing = station_list(request(data.region, '/station/list', {'page': 1, 'size': 50}, token=token))
        if row is None:
            row = DeyeConnection(user_id=user.id)
            db.add(row)
        row.region = data.region
        row.encrypted_credentials, row.encrypted_token = encrypt(credentials), encrypt(token)
        row.token_expires = expires
        if changed:
            row.dashboard_station = None
            db.query(DeyeGridHistory).filter(DeyeGridHistory.user_id == user.id).delete(synchronize_session=False)
        row.cache = {'stations': {'at': time.time(), 'page': 1, 'result': listing}}
        audit(db, user, 'deye.connect', user.id)
        db.commit()
        return public(row)


@router.delete('')
def disconnect(user=Depends(access), db=Depends(get_db)):
    section_access.require_any(user, ('deye',), db, delete=True)
    with lock_for(user):
        row = db.get(DeyeConnection, user.id)
        if row:
            db.delete(row)
        audit(db, user, 'deye.disconnect', user.id)
        db.commit()
    return {'configured': False}


@router.get('/stations')
def stations(page: int = Query(default=1, ge=1, le=1000), user=Depends(access), db=Depends(get_db)):
    with lock_for(user):
        row = connection(db, user)
        result = station_page(row, page)
        db.commit()
        return result


def station_page(row, page):
    cached = (row.cache or {}).get('stations', {})
    if cached.get('page') == page and time.time() - cached.get('at', 0) < STATION_CACHE_SECONDS:
        return cached['result']
    result = station_list(cloud(row, '/station/list', {'page': page, 'size': 50}))
    row.cache = {**(row.cache or {}), 'stations': {'at': time.time(), 'page': page, 'result': result}}
    return result


@router.put('/dashboard-station')
def set_dashboard_station(data: DashboardStationInput, user=Depends(access), db=Depends(get_db)):
    section_access.require_any(user, ('deye',), db, write=True)
    with lock_for(user):
        row = connection(db, user)
        selected = None
        if data.station_id is not None:
            if int(data.station_id) >= 2**63:
                raise HTTPException(422, 'Invalid station ID')
            # Use the account's station inventory, never a client-supplied name.
            selected = next((station for station in station_page(row, data.page)['stations']
                             if station['id'] == data.station_id), None)
            if selected is None:
                raise HTTPException(404, 'Station is not on this page. Refresh the station list and select it again.')
            selected = {'id': selected['id'], 'name': selected['name'], 'page': data.page}
        row.dashboard_station = selected
        row.cache = {key: value for key, value in (row.cache or {}).items() if key != 'monitor'}
        audit(db, user, 'deye.dashboard_station', user.id)
        db.commit()
        return {'dashboard_station': row.dashboard_station}


@router.get('/stations/{station_id}/latest')
def latest(station_id: str, user=Depends(access), db=Depends(get_db)):
    if not station_id.isascii() or not station_id.isdigit() or not 0 < int(station_id) < 2**63:
        raise HTTPException(422, 'Invalid station ID')
    with lock_for(user):
        return read_station(db, connection(db, user), station_id)


def reading_cache(row):
    # Accept caches saved by earlier versions until their next refresh.
    readings = dict((row.cache or {}).get('readings', {}))
    old = (row.cache or {}).get('latest', {})
    if old.get('station_id') and old['station_id'] not in readings:
        readings[old['station_id']] = old
    return readings


def store_reading(row, station_id, entry):
    readings = reading_cache(row)
    readings[station_id] = entry
    pinned = (row.dashboard_station or {}).get('id')
    # Bound the cache while keeping the dashboard station and latest selection.
    for key in sorted(readings, key=lambda key: readings[key].get('at', 0)):
        if len(readings) <= 8:
            break
        if key not in (pinned, station_id):
            del readings[key]
    row.cache = {key: value for key, value in (row.cache or {}).items() if key != 'latest'}
    row.cache = {**row.cache, 'readings': readings}


def cached_reading(db, user_id, station_id, cached):
    from . import deye_grid
    if cached.get('error'):
        return {'error': 'Deye Cloud is unavailable. Retrying automatically.',
                'fetched_at': cached.get('fetched_at')}
    result = normalized(cached.get('raw', {}))
    result['fetched_at'] = cached.get('fetched_at')
    result['grid_availability'] = deye_grid.cached(db, user_id, station_id)
    return result


def read_station(db, row, station_id):
    """Shared by HTTP and the background monitor, under the account lock."""
    from . import deye_grid
    cached = reading_cache(row).get(station_id, {})
    lifetime = ERROR_CACHE_SECONDS if cached.get('error') else CACHE_SECONDS
    if cached and 0 <= time.time() - cached.get('at', 0) < lifetime:
        if cached.get('error'):
            raise HTTPException(502, 'Deye Cloud is unavailable. Retrying automatically.')
        return cached_reading(db, row.user_id, station_id, cached)
    try:
        raw = cloud(row, '/station/latest', {'stationId': int(station_id)})
    except HTTPException:
        deye_grid.record(db, row.user_id, station_id, deye_grid.unknown('Cloud reading failed.'))
        store_reading(row, station_id, {'at': time.time(), 'fetched_at': now().isoformat(), 'error': True})
        db.commit()
        raise
    # Only telemetry fields are retained; raw vendor errors and private fields are excluded.
    allowed = ('lastUpdateTime', 'generationPower', 'consumptionPower', 'batteryPower', 'batterySOC',
               'gridPower', 'chargePower', 'dischargePower', 'purchasePower', 'wirePower')
    values = {key: number(raw.get(key)) for key in allowed if key != 'lastUpdateTime'}
    stamp = observation(raw.get('lastUpdateTime'))
    values['lastUpdateTime'] = stamp.isoformat() if stamp else None
    sample = deye_grid.fetch(row, station_id)
    energy = sample.get('energy', {})
    sources = {}
    # Deye inverter BatteryPower is positive when discharging, negative when charging;
    # TotalGridPower is positive for import, negative for export. Unlike some station
    # fields, these device measure points carry units and an observation timestamp.
    if 'battery' in energy:
        battery = energy['battery']
        values.update(batteryPower=battery['power'], chargePower=battery['negative'], dischargePower=battery['positive'])
        sources['battery'] = {'source': 'inverter', 'observed_at': battery['observed_at']}
    if 'grid' in energy:
        grid = energy['grid']
        values.update(gridPower=grid['power'], purchasePower=grid['positive'], wirePower=grid['negative'])
        sources['grid'] = {'source': 'inverter', 'observed_at': grid['observed_at']}
    values['power_sources'] = sources
    result = normalized(values)
    result['grid_availability'] = deye_grid.record(db, row.user_id, station_id, sample)
    store_reading(row, station_id, {'at': time.time(), 'raw': values, 'fetched_at': result['fetched_at']})
    monitor = (row.cache or {}).get('monitor', {})
    if (monitor.get('station') or {}).get('id') == station_id:
        row.cache = {**row.cache, 'monitor': {**monitor, 'error': False}}
    db.commit()
    return result


def live_snapshot(db, user):
    """Database-only, account-scoped telemetry for the authenticated live stream."""
    if user.role != 'owner' and 'deye' not in section_access.effective(user, db):
        return None
    row = db.get(DeyeConnection, user.id)
    if row is None:
        return {'configured': False}
    monitor = (row.cache or {}).get('monitor', {})
    selected = row.dashboard_station or monitor.get('station')
    readings = {}
    for station_id, cached in reading_cache(row).items():
        if not 0 <= time.time() - cached.get('at', 0) <= 90:
            readings[station_id] = {'error': 'Waiting for a new cloud reading.',
                                    'fetched_at': cached.get('fetched_at')}
        else:
            readings[station_id] = cached_reading(db, user.id, station_id, cached)
    return {'configured': True, 'dashboard_station': selected, 'readings': readings,
            'monitor_error': 'Deye Cloud is unavailable. Retrying automatically.' if monitor.get('error') else None}
