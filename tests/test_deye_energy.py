from datetime import timedelta
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
            return {'deviceDataList': [sample()]}
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
    assert result['solar_w']==57 and result['load_w']==1952
    assert result['grid_availability']['state']=='up'
    assert result['power_sources']['battery']['source']=='inverter'
    cached=client.get(PATH+'/stations/123/latest',headers=owner).json()
    assert cached['charge_w']==4976 and cached['power_sources']==result['power_sources']
    assert 'fixture' not in str(result)
