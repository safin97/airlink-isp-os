from types import SimpleNamespace as S
from airlink import system_stats as host


def test_rates_startup_reset_and_disabled_sensors(monkeypatch):
    ticks = iter([10, 10, 12, 12])
    monkeypatch.setattr(host.time, 'monotonic', lambda: next(ticks))
    monkeypatch.setattr(host.psutil, 'cpu_percent', lambda **kw: 25)
    monkeypatch.setattr(host.psutil, 'cpu_freq', lambda: None)
    monkeypatch.setattr(host.psutil, 'virtual_memory', lambda: S(total=1000, used=400, available=600, percent=40))
    monkeypatch.setattr(host.psutil, 'disk_usage', lambda _: S(total=10000, used=3000, free=7000, percent=30))
    disk = S(read_bytes=100, write_bytes=200)
    monkeypatch.setattr(host.psutil, 'disk_io_counters', lambda: disk)
    counters = {'eth0': S(bytes_recv=100, bytes_sent=200), 'lo': S(bytes_recv=9000, bytes_sent=9000)}
    monkeypatch.setattr(host.psutil, 'net_io_counters', lambda **kw: counters.copy())
    monkeypatch.setattr(host.psutil, 'net_if_stats', lambda: {
        'eth0':S(isup=True, speed=1000, flags='up'), 'lo':S(isup=True, speed=0, flags='loopback')})
    monkeypatch.setattr(host, 'gpu_readings', lambda: [{'name':'RTX', 'utilization_percent':0}])
    sampler = host.SystemStats()
    sampler.sample()
    assert sampler.snapshot['cpu_percent'] is None
    assert sampler.snapshot['network'][0]['rx_bytes_sec'] is None
    assert len(sampler.snapshot['network']) == 1
    counters['eth0'] = S(bytes_recv=2100, bytes_sent=100)  # TX counter reset
    disk = S(read_bytes=1100, write_bytes=2200)
    sampler.sample()
    data = sampler.snapshot
    assert data['cpu_percent'] == 25 and data['cpu_mhz'] is None
    assert data['network'][0]['rx_bytes_sec'] == 1000
    assert data['network'][0]['tx_bytes_sec'] is None
    assert data['disk_read_bytes_sec'] == 500 and data['disk_write_bytes_sec'] == 1000
    assert data['memory']['percent'] == 40 and data['gpus'][0]['utilization_percent'] == 0
    monkeypatch.setattr(host.time, 'monotonic', lambda: 43)
    assert sampler.read() == {'status':'stale'}


def test_dashboard_authentication_and_shared_snapshot(client, owner, monkeypatch):
    monkeypatch.setattr(host.service, 'read', lambda: {'status':'ready', 'cpu_percent':22})
    assert client.get('/api/dashboard').status_code in (401, 403)
    assert client.get('/api/dashboard', headers=owner).json()['system']['cpu_percent'] == 22


def test_unavailable_sensor_is_not_zero():
    def unavailable(): raise PermissionError('restricted sensor')
    assert host.optional(unavailable) is None
    assert host.rate(10, 20, 2) is None
    assert host.rate(20, 20, 2) == 0
