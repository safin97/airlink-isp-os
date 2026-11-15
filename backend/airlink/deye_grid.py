"""Conservative grid-voltage estimates, never inferred from zero power or logger uptime."""
import re
import time
from fastapi import HTTPException
from .models import DeyeGridHistory, now

FRESH_SECONDS = 900
MAX_POLL_GAP = 90
VOLTAGE_KEY = re.compile(r'gridvoltage(?:[abcrst123]|l[123](?:l[123])?)?')


def unknown(reason):
    return {'state': 'unknown', 'observed_at': None, 'voltages_v': [], 'reason': reason}


def from_devices(result, expected, current=None):
    from .deye import number, observation
    current = current or now()
    devices = result.get('deviceDataList')
    if not isinstance(devices, list) or len(devices) > 10:
        return unknown('Grid measurements are unavailable.')
    by_sn = {d.get('deviceSn'): d for d in devices if isinstance(d, dict) and isinstance(d.get('deviceSn'), str)}
    stamps, volts = [], []
    for serial in expected:
        device = by_sn.get(serial, {})
        stamp = observation(device.get('collectionTime'))
        if type(device.get('deviceState')) is not int or device.get('deviceState') not in (1, 2) or not stamp or not 0 <= (current - stamp).total_seconds() <= FRESH_SECONDS:
            return unknown('Inverter grid readings are missing, offline or stale.')
        points = device.get('dataList')
        if not isinstance(points, list):
            return unknown('Grid-voltage measurements are unavailable for this inverter.')
        found = []
        for point in points:
            if not isinstance(point, dict):
                continue
            key = re.sub(r'[^a-z0-9]', '', str(point.get('key', '')).lower())
            if not VOLTAGE_KEY.fullmatch(key):
                continue
            value = number(point.get('value'), nonnegative=True)
            unit = str(point.get('unit', '')).strip().lower()
            scale = {'v': 1, 'mv': .001, 'kv': 1000}.get(unit)
            if value is None or scale is None or value * scale > 1000:
                return unknown('Grid-voltage value or unit is unsupported.')
            found.append(value * scale)
        if not found:
            return unknown('Deye does not expose supported grid-voltage readings for this inverter.')
        volts.extend(found)
        stamps.append(stamp)
    if not stamps:
        return unknown('No inverter grid-voltage readings were returned.')
    # Mixed phase values and low nonzero voltage are ambiguous, not a proven outage.
    state = 'up' if all(v >= 50 for v in volts) else 'down' if all(v <= 1 for v in volts) else 'unknown'
    return {'state': state, 'observed_at': min(stamps).isoformat(), 'voltages_v': volts,
            'reason': 'Estimated from inverter grid voltage (not grid power).' if state != 'unknown'
                      else 'Grid voltages disagree or are between 1 V and 50 V.'}


def fetch(row, station_id):
    from .deye import cloud, ERROR_CACHE_SECONDS
    failed = (row.cache or {}).get('grid_error', {})
    if failed.get('station_id') == station_id and 0 <= time.time() - failed.get('at', 0) < ERROR_CACHE_SECONDS:
        return unknown('Grid measurements unavailable. Retrying automatically.')
    try:
        inventory = (row.cache or {}).get('grid_devices', {})
        if inventory.get('station_id') != station_id or time.time() - inventory.get('at', 0) >= 1800:
            result = cloud(row, '/station/device', {'stationIds': [int(station_id)], 'page': 1, 'size': 200})
            items = result.get('deviceListItems')
            if not isinstance(items, list) or len(items) > 200 or not isinstance(result.get('total'), int) or result['total'] > len(items):
                return unknown('A complete inverter inventory is required for grid monitoring.')
            serials = sorted({d['deviceSn'] for d in items if isinstance(d, dict)
                              and d.get('deviceType') == 'INVERTER' and str(d.get('stationId')) == station_id
                              and isinstance(d.get('deviceSn'), str) and 0 < len(d['deviceSn']) <= 128})
            inventory = {'station_id': station_id, 'at': time.time(), 'serials': serials}
            row.cache = {**(row.cache or {}), 'grid_devices': inventory}
        serials = inventory['serials']
        if not serials or len(serials) > 10:
            return unknown('Grid monitoring requires a station with 1–10 supported inverters.')
        result = cloud(row, '/device/latest', {'deviceList': serials, 'deviceType': 'INVERTER'})
        return from_devices(result, serials)
    except HTTPException:
        row.cache = {**(row.cache or {}), 'grid_error': {'station_id': station_id, 'at': time.time()}}
        return unknown('Grid measurements unavailable. Check Deye device-monitoring access or cloud connectivity.')


def record(db, user_id, station_id, sample, current=None):
    from .deye import observation
    current = current or now()
    row = db.get(DeyeGridHistory, (user_id, station_id))
    if row is None:
        row = DeyeGridHistory(user_id=user_id, station_id=station_id, history={})
        db.add(row)
    history = dict(row.history)
    stamp = observation(sample.get('observed_at'))
    state = sample.get('state', 'unknown')
    if stamp is None or not 0 <= (current - stamp).total_seconds() <= FRESH_SECONDS:
        state = 'unknown'
        stamp = None
    previous = observation(history.get('sample_at'))
    last_poll = observation(history.get('poll_at'))
    continuous = last_poll is not None and 0 <= (current - last_poll).total_seconds() <= MAX_POLL_GAP
    if stamp and previous and stamp < previous:
        state = 'unknown'
    tracking_from = observation(history.get('tracking_from')) or current
    if not continuous or not history.get('eligible') or history.get('state') != state:
        tracking_from = current
    # Count only intervals bounded by two distinct, fresh, equal-state samples
    # collected while polling stayed continuous. Repeated cloud samples add nothing.
    if (state in ('up', 'down') and history.get('state') == state and history.get('eligible') and continuous and stamp and previous
            and 0 < (stamp - previous).total_seconds() <= FRESH_SECONDS):
        key = state + '_seconds'
        history[key] = history.get(key, 0) + max(0, (stamp - max(previous, tracking_from)).total_seconds())
    started = history.get('started_at') or current.isoformat()
    eligible = state in ('up', 'down') and stamp is not None and (previous is None or stamp > previous
                or (continuous and history.get('eligible', False) and history.get('state') == state and stamp == previous))
    history.update(started_at=started, state=state, poll_at=current.isoformat(), eligible=eligible, tracking_from=tracking_from.isoformat(),
                   sample_at=max(filter(None, [stamp, previous])).isoformat() if stamp or previous else None,
                   reason=sample.get('reason'), voltages_v=sample.get('voltages_v', []))
    row.history = history
    return public(history, current)


def public(history, current=None):
    from .deye import observation
    current = current or now()
    started = observation(history.get('started_at'))
    sample = observation(history.get('sample_at'))
    poll = observation(history.get('poll_at'))
    state = history.get('state', 'unknown')
    if not sample or not poll or not 0 <= (current - sample).total_seconds() <= FRESH_SECONDS or (current - poll).total_seconds() > MAX_POLL_GAP:
        state = 'unknown'
    up, down = history.get('up_seconds', 0), history.get('down_seconds', 0)
    return {'state': state, 'uptime_seconds': up, 'downtime_seconds': down,
            'unknown_seconds': max(0, (current - started).total_seconds() - up - down) if started else 0,
            'started_at': history.get('started_at'), 'observed_at': history.get('sample_at'),
            'voltages_v': history.get('voltages_v', []), 'reason': history.get('reason'),
            'method': 'voltage_estimate', 'scope': 'observed_samples'}


def cached(db, user_id, station_id):
    row = db.get(DeyeGridHistory, (user_id, station_id))
    return public(row.history if row else {})
