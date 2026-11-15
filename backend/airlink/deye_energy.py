"""Power flows from explicit Deye inverter measurements (W/kW), not station-name guesses."""
from .models import now


def from_devices(result, expected, current=None):
    from .deye import number, observation
    current = current or now()
    devices = result.get('deviceDataList')
    if not expected or not isinstance(devices, list) or len(devices) > 10:
        return {}
    by_sn = {d.get('deviceSn'): d for d in devices if isinstance(d, dict) and isinstance(d.get('deviceSn'), str)}
    if len(by_sn) != len(devices) or set(by_sn) != set(expected):
        return {}
    readings, stamps = [], []
    for serial in expected:
        device = by_sn.get(serial, {})
        stamp = observation(device.get('collectionTime'))
        if (type(device.get('deviceState')) is not int or device.get('deviceState') not in (1, 2)
                or not stamp or not 0 <= (current - stamp).total_seconds() <= 900):
            return {}
        points = device.get('dataList')
        if not isinstance(points, list):
            return {}
        values = {}
        for key in ('BatteryPower', 'TotalGridPower'):
            matches = [p for p in points if isinstance(p, dict) and p.get('key') == key]
            if len(matches) != 1:
                continue
            point = matches[0]
            value = number(point.get('value'))
            scale = {'w': 1, 'kw': 1000}.get(str(point.get('unit', '')).strip().lower())
            if value is not None and scale is not None and abs(value * scale) <= 1e9:
                values[key] = value * scale
        readings.append(values)
        stamps.append(stamp)
    # Require complete coverage: partial station sums must never look like totals.
    result = {}
    for name, key in [('battery', 'BatteryPower'), ('grid', 'TotalGridPower')]:
        if all(key in values for values in readings):
            powers = [values[key] for values in readings]
            result[name] = {'power': sum(powers), 'positive': sum(max(0, p) for p in powers),
                            'negative': sum(max(0, -p) for p in powers),
                            'observed_at': min(stamps).isoformat()}
    return result
