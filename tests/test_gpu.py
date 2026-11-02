import subprocess
from pathlib import Path
from console import gpu


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
