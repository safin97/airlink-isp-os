from datetime import timedelta
import pytest
from airlink import deye, deye_energy
from airlink.models import now
from test_deye import cloud, CONFIG, PATH


def sample(battery=-4976, grid=7163, unit='W', state=1, stamp=None, serial='fixture'):
    return {'deviceSn': serial, 'deviceState': state, 'collectionTime': (stamp or now()).timestamp(),
            'dataList': [{'key': 'BatteryPower', 'value': battery, 'unit': unit},
                         {'key': 'TotalGridPower', 'value': grid, 'unit': unit},
                         {'key': 'GridVoltageL1', 'value': 203.2, 'unit': 'V'}]}


def test_device_power_signs_units_and_complete_station_coverage():
    assert deye.normalized({'wirePower':6891, 'purchasePower':None})['export_w'] is None
    result = deye_energy.from_devices({'deviceDataList': [sample()]}, ['fixture'])
    assert result['battery']['negative'] == 4976 and result['battery']['positive'] == 0
    assert result['grid']['positive'] == 7163 and result['grid']['negative'] == 0
    result = deye_energy.from_devices({'deviceDataList': [sample(2, -3, 'kW')]}, ['fixture'])
    assert result['battery']['positive'] == 2000 and result['battery']['negative'] == 0
    assert result['grid']['negative'] == 3000 and result['grid']['power'] == -3000
    assert deye_energy.from_devices({'deviceDataList': [sample(), sample()]}, ['fixture']) == {}
    devices = [sample(-1000, 2000), sample(500, -300, serial='second')]
    result = deye_energy.from_devices({'deviceDataList': devices}, ['fixture', 'second'])
    assert result['battery']['power'] == -500
    assert result['battery']['positive'] == 500 and result['battery']['negative'] == 1000
    assert result['grid']['power'] == 1700
    assert deye_energy.from_devices({'deviceDataList': devices[:1]}, ['fixture', 'second']) == {}
    for device in [sample(state=3), sample(state=True), sample(stamp=now()-timedelta(minutes=16)), sample(unit='A'), sample(battery='NaN', grid=True)]:
        assert deye_energy.from_devices({'deviceDataList': [device]}, ['fixture']) == {}
    device=sample(); device['dataList'].append({'key':'BatteryPower','value':999,'unit':'W'})
    assert 'battery' not in deye_energy.from_devices({'deviceDataList':[device]}, ['fixture'])


def test_explicit_device_power_repairs_incomplete_signed_station_fields(client, owner, cloud, monkeypatch):
    original = deye.request
    def request(region, path, body, **kwargs):
        if path == '/station/device':
            return {'deviceListItems': [{'stationId':123,'deviceType':'INVERTER','deviceSn':'fixture'}], 'total':1}
        if path == '/device/latest':
            device = sample()
            device['dataList'] += load_points()
            return {'deviceDataList': [device]}
        if path == '/station/latest':
            return {'lastUpdateTime':now().isoformat(), 'batteryPower':-4976,'chargePower':-4976,
                    'dischargePower':None,'wirePower':6891,'gridPower':None,'purchasePower':None,
                    'generationPower':57,'consumptionPower':1952}
        return original(region,path,body,**kwargs)
    monkeypatch.setattr(deye,'request',request)
    client.put(PATH,headers=owner,json=CONFIG)
    result=client.get(PATH+'/stations/123/latest',headers=owner).json()
    assert result['battery_w']==-4976 and result['charge_w']==4976 and result['discharge_w']==0
    assert result['grid_w']==7163 and result['import_w']==7163 and result['export_w']==0
    assert result['solar_w']==57 and result['load_w']==798
    assert result['load_current']['current_a'] == pytest.approx(798 / 224.2)
    assert result['load_current']['source'] == 'estimated'
    assert result['grid_availability']['state']=='up'
    assert result['power_sources']['battery']['source']=='inverter'
    cached=client.get(PATH+'/stations/123/latest',headers=owner).json()
    assert cached['charge_w']==4976 and cached['power_sources']==result['power_sources']
    assert cached['load_current'] == result['load_current']
    assert cached['load_w'] == 798
    assert 'fixture' not in str(result)


def load_points(power=798, voltage=224.2):
    return [{'key': 'TotalConsumptionPower', 'value': power, 'unit': 'W'},
            {'key': 'LoadVoltageL1L2', 'value': voltage, 'unit': 'V'}]


def test_load_current_measured_preferred_and_estimate_units():
    stamp = now().isoformat()
    estimate = deye_energy.load_from_points(load_points(), stamp)
    assert estimate == {'current_a': pytest.approx(798 / 224.2), 'source': 'estimated',
                        'power': 798, 'voltage_v': 224.2, 'observed_at': stamp}
    assert deye_energy.load_from_points(load_points(power=0), stamp)['current_a'] == 0
    points = load_points()
    points[0].update(value=.798, unit='kW')
    points[1].update(value=224200, unit='mV')
    converted = deye_energy.load_from_points(points, stamp)
    assert converted['current_a'] == pytest.approx(estimate['current_a'])
    assert converted['voltage_v'] == pytest.approx(estimate['voltage_v'])
    assert converted['source'] == 'estimated' and converted['power'] == 798
    for value, unit in [(4.2, 'A'), (4200, 'mA')]:
        measured = deye_energy.load_from_points(points + [{'key': 'LoadCurrent', 'value': value, 'unit': unit}], stamp)
        assert measured['source'] == 'measured' and measured['current_a'] == 4.2


@pytest.mark.parametrize('value', [None, True, 'NaN', 'inf', -1, 0, 49, 501])
def test_load_current_rejects_invalid_voltage(value):
    assert deye_energy.load_from_points(load_points(voltage=value), now().isoformat()) is None


def test_load_current_rejects_ambiguous_or_unsupported_measurements():
    stamp = now().isoformat()
    for extra in [load_points()[0], load_points()[1],
                  {'key': 'ACVoltageSUB', 'value': 230, 'unit': 'V'},
                  {'key': 'LoadCurrentL2', 'value': 2, 'unit': 'A'},
                  {'key': 'LoadCurrent', 'value': True, 'unit': 'A'},
                  {'key': 'LoadCurrent', 'value': 4, 'unit': 'W'}]:
        assert deye_energy.load_from_points(load_points() + [extra], stamp) is None
    assert deye_energy.load_from_points([{'key': 'ACCurrentRUA', 'value': 4, 'unit': 'A'}], stamp) is None
    for power in [True, -1, 'NaN', 'inf', 1e10]:
        assert deye_energy.load_from_points(load_points(power=power), stamp) is None
    device = sample()
    device['dataList'] += load_points()
    assert 'load' in deye_energy.from_devices({'deviceDataList': [device]}, ['fixture'])
    second = {**device, 'deviceSn': 'second'}
    assert 'load' not in deye_energy.from_devices({'deviceDataList': [device, second]}, ['fixture', 'second'])
    for changes in [{'deviceState': 3}, {'collectionTime': (now()-timedelta(minutes=16)).timestamp()}]:
        assert 'load' not in deye_energy.from_devices({'deviceDataList': [{**device, **changes}]}, ['fixture'])
