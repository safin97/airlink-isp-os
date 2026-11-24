import subprocess
from pathlib import Path
import pytest
from console import gpu


@pytest.fixture(autouse=True)
def isolated_pci_database(monkeypatch):
    monkeypatch.setattr(gpu, 'PCI_DATABASES', ())
    gpu._pci_models.cache_clear()


def device(root, bus, vendor='0x10de', device_id='0x2484', driver='nvidia', kind='0x030000'):
    path = root / bus
    path.mkdir()
    for name, value in [('vendor', vendor), ('device', device_id), ('class', kind)]:
        (path / name).write_text(value)
    if driver:
        (path / 'driver').symlink_to(root / 'drivers' / driver)
    return path


def test_no_gpu_and_non_graphics_devices_do_not_run_tools(tmp_path, monkeypatch):
    device(tmp_path, '0000:01:00.0', kind='0x020000')
    monkeypatch.setattr(gpu, 'command', lambda args: (_ for _ in ()).throw(AssertionError(args)))
    assert gpu.detect(tmp_path) == []


def test_rtx_auto_detection_matches_pci_address_and_telemetry(tmp_path, monkeypatch):
    device(tmp_path, '0000:01:00.0')
    device(tmp_path, '0000:02:00.0', device_id='0x2684')
    def command(args):
        if args[0] == 'lspci':
            return '0000:01:00.0 "VGA compatible controller" "NVIDIA Corporation" "GA104 [GeForce RTX 3070]"\n'
        return ('00000000:02:00.0, NVIDIA GeForce RTX 4090, 610.57.04, 24564, 10, 0, 32\n'
                '00000000:01:00.0, NVIDIA GeForce RTX 3070, 610.57.04, 8192, 150, 12, 42\n')
    monkeypatch.setattr(gpu, 'command', command)
    first, second = gpu.detect(tmp_path)
    assert first['name'] == 'NVIDIA GeForce RTX 3070'
    assert first['status'] == 'ready' and first['driver'] == 'nvidia'
    assert first['memory_total_mib'] == 8192 and first['memory_used_mib'] == 150
    assert first['temperature_c'] == 42 and first['utilization_percent'] == 12
    assert second['name'] == 'NVIDIA GeForce RTX 4090' and second['utilization_percent'] == 0


def test_missing_driver_does_not_claim_acceleration(tmp_path, monkeypatch):
    device(tmp_path, '0000:01:00.0', driver=None)
    monkeypatch.setattr(gpu, 'command', lambda args: '')
    result = gpu.detect(tmp_path)[0]
    assert result['vendor'] == 'NVIDIA' and result['status'] == 'not_loaded'
    assert result['utilization_percent'] is None


def test_gtx_1660_ti_name_fallback_does_not_claim_driver_is_working(tmp_path, monkeypatch):
    device(tmp_path, '0000:01:00.0', device_id='0x2191', driver=None)
    monkeypatch.setattr(gpu, 'command', lambda args: '')
    result = gpu.detect(tmp_path)[0]
    assert result['name'] == 'NVIDIA GeForce GTX 1660 Ti (laptop)'
    assert result['status'] == 'not_loaded'
    assert result['utilization_percent'] is None and result['driver_version'] is None


def test_intel_fallback_and_unavailable_nvidia_metrics(tmp_path, monkeypatch):
    device(tmp_path, '0000:00:02.0', vendor='0x8086', driver='i915')
    device(tmp_path, '0000:01:00.0')
    monkeypatch.setattr(gpu, 'command', lambda args: '' if args[0] == 'lspci' else
        '00000000:01:00.0, NVIDIA RTX, 610.57.04, N/A, nan, -1, [Not Supported]\n')
    intel, nvidia = gpu.detect(tmp_path)
    assert intel['status'] == 'loaded' and intel['driver'] == 'i915'
    assert nvidia['status'] == 'ready'
    assert all(nvidia[key] is None for key in ('memory_total_mib', 'memory_used_mib', 'temperature_c', 'utilization_percent'))


def test_missing_tool_timeout_and_driver_failure_are_nonfatal(monkeypatch):
    monkeypatch.setattr(gpu.shutil, 'which', lambda name: None)
    assert gpu.command(['nvidia-smi']) == ''
    monkeypatch.setattr(gpu.shutil, 'which', lambda name: '/usr/bin/' + name)
    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(args[0], 3)
    monkeypatch.setattr(gpu.subprocess, 'run', timeout)
    assert gpu.command(['nvidia-smi']) == ''
    monkeypatch.setattr(gpu.subprocess, 'run', lambda *a, **k: subprocess.CompletedProcess(a, 1, '', 'No devices'))
    assert gpu.command(['nvidia-smi']) == ''


def test_sampler_caches_names_but_refreshes_driver_and_utilization(tmp_path, monkeypatch):
    path = device(tmp_path, '0000:01:00.0')
    stamp = [0]
    utilization = [10]
    calls = []
    def command(args):
        calls.append(args[0])
        if args[0] == 'lspci':
            return '0000:01:00.0 "VGA compatible controller" "NVIDIA" "RTX"\n'
        return f'00000000:01:00.0, NVIDIA RTX, 610.57.04, 8192, 10, {utilization[0]}, 32\n'
    monkeypatch.setattr(gpu, 'command', command)
    monkeypatch.setattr(gpu.time, 'monotonic', lambda: stamp[0])
    sampler = gpu.Sampler(tmp_path)
    assert sampler.read()[0]['utilization_percent'] == 10
    stamp[0] = 3; utilization[0] = 25
    assert sampler.read()[0]['utilization_percent'] == 25
    assert calls.count('lspci') == 1 and calls.count('nvidia-smi') == 2
    stamp[0] = 60
    sampler.read()
    assert calls.count('lspci') == 2
    (path / 'driver').unlink()
    reading = sampler.read()[0]
    assert reading['status'] == 'not_loaded' and reading['utilization_percent'] is None


def test_numeric_lspci_name_cannot_replace_known_gtx_model(tmp_path, monkeypatch):
    device(tmp_path, '0000:01:00.0', device_id='0x2191', driver=None)
    monkeypatch.setattr(gpu, 'command', lambda args:
        '0000:01:00.0 "3D controller" "NVIDIA Corporation" "Device 2191"\n' if args[0] == 'lspci' else '')
    result = gpu.detect(tmp_path)[0]
    assert result['name'] == 'NVIDIA GeForce GTX 1660 Ti (laptop)'
    assert result['status'] == 'not_loaded'


def test_offline_database_identifies_multiple_gpus_without_lspci_or_drivers(tmp_path, monkeypatch):
    root = tmp_path / 'devices'
    root.mkdir()
    device(root, '0000:00:02.0', vendor='0x8086', device_id='0x1234', driver=None)
    device(root, '0000:01:00.0', vendor='0x1002', device_id='0x5678', driver=None)
    database = tmp_path / 'pci.ids'
    # Synthetic fixtures exercise vendor/device/subsystem/class parsing.
    database.write_text('8086  Intel Corporation\n\t1234  Test Integrated Graphics\n'
                        '\t\t0001 0002  Board name must not replace GPU\n'
                        '1002  Advanced Micro Devices\n\t5678  Test Radeon Graphics\n'
                        'C 03  Display controller\n\t1234  Not a GPU model\n')
    monkeypatch.setattr(gpu, 'PCI_DATABASES', (tmp_path / 'missing', database))
    monkeypatch.setattr(gpu, 'command', lambda args: '')
    readings = gpu.detect(root)
    assert [row['name'] for row in readings] == ['Intel Test Integrated Graphics', 'AMD Test Radeon Graphics']
    assert all(row['status'] == 'not_loaded' and row['utilization_percent'] is None for row in readings)
    gpu.detect(root)
    assert gpu._pci_models.cache_info().hits == 1
    database.write_text(database.read_text().replace('Test Integrated Graphics', 'Updated Integrated Graphics'))
    assert gpu.detect(root)[0]['name'] == 'Intel Updated Integrated Graphics'


def test_real_lspci_name_wins_over_offline_database(tmp_path, monkeypatch):
    device(tmp_path, '0000:01:00.0', driver=None)
    monkeypatch.setattr(gpu, 'pci_model_names', lambda unresolved: {} if not unresolved else pytest.fail('Unexpected database lookup'))
    monkeypatch.setattr(gpu, 'command', lambda args: '')
    assert gpu.detect(tmp_path, name_lookup=lambda: {'0000:01:00.0': 'NVIDIA Specific Model'})[0]['name'] == 'NVIDIA Specific Model'


def test_unavailable_nvidia_name_preserves_detected_model(tmp_path, monkeypatch):
    device(tmp_path, '0000:01:00.0', device_id='0x2191')
    monkeypatch.setattr(gpu, 'command', lambda args: '' if args[0] == 'lspci' else
        '00000000:01:00.0, N/A, 610.1, 6144, 10, 0, 40\n')
    result = gpu.detect(tmp_path)[0]
    assert result['name'] == 'NVIDIA GeForce GTX 1660 Ti (laptop)'
    assert result['utilization_percent'] == 0


def test_unknown_id_stays_explicit_and_does_not_inherit_another_model(tmp_path, monkeypatch):
    device(tmp_path, '0000:01:00.0', device_id='0xffff', driver=None)
    monkeypatch.setattr(gpu, 'command', lambda args: '')
    assert gpu.detect(tmp_path)[0]['name'] == 'NVIDIA 0xffff'
