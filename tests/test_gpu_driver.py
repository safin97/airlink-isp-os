from types import SimpleNamespace

import pytest
from updates import gpu_driver


@pytest.fixture
def machine(monkeypatch):
    cards = [{'vendor_id': '0x10de', 'device_id': '0x2191', 'driver': None, 'status': 'not_loaded'}]
    installed = set()
    unavailable = set()
    calls = []
    monkeypatch.setattr(gpu_driver, 'detect', lambda: cards)
    monkeypatch.setattr(gpu_driver.platform, 'machine', lambda: 'x86_64')
    monkeypatch.setattr(gpu_driver.platform, 'release', lambda: '6.12.1-amd64')

    def run(command, **kwargs):
        calls.append(command)
        if command[0] == 'dpkg-query':
            return 'installed' if command[-1] in installed else ''
        assert command[:2] == ['apt-cache', 'policy']  # Planning never mutates the PC.
        return '  Candidate: (none)\n' if command[-1] in unavailable else '  Candidate: 610.1-1\n'

    return SimpleNamespace(cards=cards, installed=installed, unavailable=unavailable, calls=calls, run=run)


def test_official_driver_includes_current_and_future_kernel_headers_and_graphics(machine):
    plan = gpu_driver.missing_driver_plan(machine.run)
    assert plan['kernel'] == '6.12.1-amd64'
    assert set(plan['targets']) == {name + '=610.1-1' for name in (
        'nvidia-open', 'linux-headers-6.12.1-amd64', 'linux-headers-amd64',
        'pciutils', 'mesa-utils', 'libgl1-mesa-dri')}
    assert 'Restart after installation' in plan['message']


def test_older_debian_install_uses_complete_debian_driver_set(machine):
    machine.unavailable.add('nvidia-open')
    plan = gpu_driver.missing_driver_plan(machine.run)
    assert {'nvidia-open-kernel-dkms=610.1-1', 'nvidia-driver=610.1-1', 'nvidia-smi=610.1-1'} <= set(plan['targets'])
    assert 'nvidia-open=610.1-1' not in plan['targets']


@pytest.mark.parametrize('missing', ['linux-headers-6.12.1-amd64', 'mesa-utils', 'nvidia-driver'])
def test_incomplete_repository_never_offers_partial_driver_install(machine, missing):
    machine.unavailable.update({'nvidia-open', missing})
    plan = gpu_driver.missing_driver_plan(machine.run)
    assert plan['targets'] == [] and plan['kernel'] is None
    assert missing in plan['message']


@pytest.mark.parametrize('package', ['nvidia-open', 'cuda-drivers', 'nvidia-driver', 'nvidia-kernel-dkms'])
def test_preserves_existing_driver_family_even_if_telemetry_is_unavailable(machine, package):
    machine.installed.add(package)
    plan = gpu_driver.missing_driver_plan(machine.run)
    assert plan['targets'] == []
    assert 'packages are installed' in plan['message']
    assert not any(call[0] == 'apt-cache' for call in machine.calls)


def test_working_driver_needs_no_package_changes(machine):
    machine.cards[0].update(driver='nvidia', status='ready')
    plan = gpu_driver.missing_driver_plan(machine.run)
    assert plan['targets'] == [] and 'responding' in plan['message']
    assert machine.calls == []


def test_unmanaged_loaded_driver_is_not_overwritten(machine):
    machine.cards[0]['driver'] = 'nvidia'
    plan = gpu_driver.missing_driver_plan(machine.run)
    assert plan['targets'] == [] and 'unmanaged' in plan['message']


def test_other_gpu_models_do_not_receive_gtx_driver_plan(machine):
    machine.cards[0]['device_id'] = '0x1180'
    assert gpu_driver.missing_driver_plan(machine.run) is None
    assert not machine.calls


def test_mixed_nvidia_generations_require_compatibility_review(machine):
    machine.cards.append({'vendor_id': '0x10de', 'device_id': '0x1180'})
    plan = gpu_driver.missing_driver_plan(machine.run)
    assert plan['targets'] == [] and 'Multiple NVIDIA' in plan['message']
    assert not machine.calls
