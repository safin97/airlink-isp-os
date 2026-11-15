"""Deye inverter power flows and load current, with explicit W/V estimate metadata."""
from .models import now


def load_from_points(points, stamp):
    """One inverter / one output only. Never sum phase or inverter amperages."""
    from .deye import number

    def value(point, units, maximum):
        amount = number(point.get('value'), nonnegative=True)
        scale = units.get(str(point.get('unit', '')).strip().lower())
        return amount * scale if amount is not None and scale is not None and amount * scale <= maximum else None

    points = [p for p in points if isinstance(p, dict)]
    # Known additional output phases make a single W/V value ambiguous.
    if any(p.get('key') in ('ACVoltageSUB', 'ACVoltageTWC', 'LoadVoltageL2', 'LoadVoltageL3',
                            'LoadCurrentL2', 'LoadCurrentL3', 'LoadVoltageL2L3', 'LoadVoltageL3L1') for p in points):
        return None
    powers = [p for p in points if p.get('key') == 'TotalConsumptionPower']
    power = value(powers[0], {'w': 1, 'kw': 1000}, 1e9) if len(powers) == 1 else None
    currents = [p for p in points if str(p.get('key', '')).startswith('LoadCurrent')]
    if currents:
        if len(currents) != 1 or currents[0].get('key') not in ('LoadCurrent', 'LoadCurrentL1', 'LoadCurrentL1L2'):
            return None
        amps = value(currents[0], {'a': 1, 'ma': .001}, 10000)
        return {'current_a': amps, 'source': 'measured', 'power': power, 'observed_at': stamp} if amps is not None else None
    voltages = [p for p in points if str(p.get('key', '')).startswith('LoadVoltage')]
    if len(voltages) != 1 or voltages[0].get('key') not in ('LoadVoltage', 'LoadVoltageL1', 'LoadVoltageL1L2'):
        return None
    voltage = value(voltages[0], {'v': 1, 'mv': .001, 'kv': 1000}, 500)
    if power is None or voltage is None or voltage < 50 or power / voltage > 10000:
        return None
    return {'current_a': power / voltage, 'source': 'estimated', 'power': power,
            'voltage_v': voltage, 'observed_at': stamp}


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
    if len(expected) == 1:
        load = load_from_points(points, stamps[0].isoformat())
        if load is not None:
            result['load'] = load
    return result
