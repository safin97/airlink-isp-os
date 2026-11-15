import subprocess
from console import driver_health as health


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def device(root, bus, name, driver=None, module=None, **attributes):
    path = root / 'bus' / bus / 'devices' / name
    path.mkdir(parents=True)
    for key, value in attributes.items():
        write(path / key, value)
    if driver:
        target = root / 'bus' / bus / 'drivers' / driver
        target.mkdir(parents=True, exist_ok=True)
        (path / 'driver').symlink_to(target)
        if module:
            mod = root / 'module' / module
            mod.mkdir(parents=True, exist_ok=True)
            (target / 'module').symlink_to(mod)
    return path


def test_bound_missing_optional_and_nvidia_telemetry(tmp_path, monkeypatch):
    monkeypatch.setattr(health, 'pci_names', lambda: {'0000:01:00.0': 'NVIDIA RTX'})
    device(tmp_path, 'pci', '0000:01:00.0', 'nvidia', 'nvidia', **{'class': '0x030000'})
    device(tmp_path, 'pci', '0000:02:00.0', **{'class': '0x020000'})
    device(tmp_path, 'pci', '0000:00:01.0', **{'class': '0x060000'})
    write(tmp_path / 'module/nvidia/version', '610.1')
    write(tmp_path / 'module/nvidia/initstate', 'live')
    result = health.collect([{'pci_address': '0000:01:00.0', 'status': 'ready',
                              'utilization_percent': 0, 'temperature_c': 42}], tmp_path)
    by_id = {item['id']: item for item in result['devices']}
    gpu = by_id['pci/0000:01:00.0']
    assert gpu['status'] == 'loaded' and gpu['version'] == '610.1'
    assert 'GPU usage: 0%' in gpu['metrics']
    assert by_id['pci/0000:02:00.0']['status'] == 'warning'
    assert by_id['pci/0000:00:01.0']['status'] == 'unknown'
    assert result['counts'] == {'loaded': 1, 'warning': 1, 'unknown': 2}
    assert result['modules'][0]['status'] == 'loaded'
    assert health.collect([], tmp_path)['counts']['loaded'] == 0


def test_usb_platform_builtin_cpu_and_module_transition(tmp_path, monkeypatch):
    monkeypatch.setattr(health, 'pci_names', lambda: {})
    device(tmp_path, 'usb', '1-1', 'usb', authorized='0', product='USB device')
    device(tmp_path, 'platform', 'serial8250', 'serial8250')
    device(tmp_path, 'virtio', 'virtio0', 'virtio_net', 'virtio_net')
    write(tmp_path / 'module/virtio_net/initstate', 'going')
    write(tmp_path / 'module/builtin/parameters/example', 'not returned')
    write(tmp_path / 'devices/system/cpu/cpufreq/policy0/scaling_driver', 'intel_pstate')
    write(tmp_path / 'devices/system/cpu/cpufreq/policy0/scaling_governor', 'powersave')
    write(tmp_path / 'devices/system/cpu/cpu0/microcode/version', '0x123')
    result = health.collect(sys_root=tmp_path)
    by_id = {item['id']: item for item in result['devices']}
    assert by_id['usb/1-1']['status'] == 'warning'
    assert by_id['platform/serial8250']['status'] == 'loaded'
    assert by_id['platform/serial8250']['version'] is None
    assert by_id['virtio/virtio0']['status'] == 'warning'
    cpu = by_id['cpu/power-management']
    assert cpu['driver'] == 'intel_pstate' and cpu['status'] == 'loaded'
    assert cpu['metrics'] == ['Governor: powersave', 'CPU 0 microcode: 0x123']
    assert 'not returned' not in str(result)


def test_unavailable_and_partial_inventory_are_explicit(tmp_path, monkeypatch):
    monkeypatch.setattr(health, 'pci_names', lambda: {})
    assert health.collect(sys_root=tmp_path)['status'] == 'unavailable'
    for index in range(4):
        device(tmp_path, 'platform', str(index))
    monkeypatch.setattr(health, 'LIMIT', 2)
    result = health.collect(sys_root=tmp_path)
    assert result['status'] == 'partial' and result['truncated']
    assert len(result['devices']) == 3  # Two bus devices and one CPU summary.


def test_disappearing_device_is_not_reported_as_loaded(tmp_path, monkeypatch):
    monkeypatch.setattr(health, 'pci_names', lambda: {})
    path = device(tmp_path, 'platform', 'gone')
    (path / 'driver').symlink_to(tmp_path / 'missing')
    assert health.collect(sys_root=tmp_path)['devices'][0]['status'] == 'unknown'


def test_missing_or_hung_pci_tool_does_not_break_inventory(monkeypatch):
    for error in (FileNotFoundError(), subprocess.TimeoutExpired('lspci', 2)):
        def fail(*a, **kw):
            raise error
        monkeypatch.setattr(health.subprocess, 'run', fail)
        assert health.pci_names() == {}
