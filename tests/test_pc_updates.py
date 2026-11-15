from types import SimpleNamespace
import time
import pytest
from airlink import api
from test_api import user
from updates import pc, update


@pytest.fixture
def system(tmp_path, monkeypatch):
    monkeypatch.setattr(pc, 'ROOT', tmp_path / 'pc-updates')
    monkeypatch.setattr(update, 'ROOT', tmp_path / 'updates')
    monkeypatch.setattr(pc, 'DPKG_STATUS', tmp_path / 'dpkg-status')
    pc.DPKG_STATUS.write_text('installed package state')
    monkeypatch.setattr(pc, 'supported', lambda: True)
    monkeypatch.setattr(pc, 'boot_id', lambda: 'boot-one')
    monkeypatch.setattr(update, 'restart_status', lambda: {'pending': False})
    monkeypatch.setattr(pc.os, 'geteuid', lambda: 0)
    monkeypatch.setattr(pc.subprocess, 'run', lambda *a, **kw: SimpleNamespace(returncode=0))
    monkeypatch.setattr(update, 'health_check', lambda: None)
    monkeypatch.setattr(pc.shutil, 'disk_usage', lambda path: SimpleNamespace(free=10 * 1024**3))
    packages = pc.parse_plan('Inst linux-image-amd64 [6.1] (6.2 Debian:13/stable [amd64])\nConf linux-image-amd64 (6.2)')
    plan = {'id': 'reviewed-plan', 'packages': packages, 'fingerprint': pc.fingerprint(),
            'expires': time.time() + 3600, 'checked_at': time.time()}
    update.atomic(pc.ROOT / 'plan.json', plan)
    pc.write_state('ready')
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        if '--simulate' in command:
            return 'Inst linux-image-amd64 [6.1] (6.2 Debian:13/stable [amd64])'
        return ''
    monkeypatch.setattr(pc, 'run', run)
    return plan, calls


def test_owner_only_api_and_fixed_payload(client, owner, monkeypatch):
    _, manager = user(client, owner, 'manager', 'pc-manager')
    calls = []
    monkeypatch.setattr(api, 'broker', lambda name, payload=None: calls.append((name, payload)) or {'supported': True})
    path = '/api/system/pc-updates'
    assert client.get(path, headers=manager).status_code == 403
    assert client.post(path + '/install', headers=manager, json={'confirm': True, 'plan_id': 'id'}).status_code == 403
    assert client.get(path).status_code == 401
    assert client.post(path + '/install', headers=owner, json={}).status_code == 422
    assert client.post(path + '/shell', headers=owner, json={}).status_code == 404
    assert not calls
    assert client.post(path + '/check', headers=owner, json={'command': 'arbitrary'}).status_code == 202
    assert calls[-1] == ('pc-updates.check', {})
    assert client.post(path + '/install', headers=owner,
                       json={'confirm': True, 'plan_id': 'id', 'command': 'arbitrary'}).status_code == 202
    assert calls[-1] == ('pc-updates.install', {'confirm': True, 'plan_id': 'id'})


@pytest.mark.parametrize('text', ['Remv libc6 [1.0]', 'Purg example [1]',
    'Inst --shell (1.0)', 'Inst example (1.0;evil)', 'Inst airlink-isp-os [1] (2 repo)'])
def test_removals_invalid_targets_and_airlink_package_rejected(system, text):
    with pytest.raises(ValueError):
        pc.parse_plan(text)


def test_plan_rejects_downgrades(system, monkeypatch):
    monkeypatch.setattr(pc.subprocess, 'run', lambda *a, **kw: SimpleNamespace(returncode=1))
    with pytest.raises(ValueError, match='downgrade'):
        pc.parse_plan('Inst example [2.0] (1.0 repo)')


def test_review_is_required_and_bound_to_package_state(system):
    plan, calls = system
    with pytest.raises(ValueError, match='confirm'):
        pc.action('install', {'plan_id': plan['id']})
    with pytest.raises(ValueError, match='changed'):
        pc.action('install', {'confirm': True, 'plan_id': 'different'})
    pc.DPKG_STATUS.write_text('changed outside AirLink')
    with pytest.raises(ValueError, match='changed'):
        pc.action('install', {'confirm': True, 'plan_id': plan['id']})
    assert calls == []


def test_expired_plan_cannot_queue(system):
    plan, calls = system
    plan['expires'] = time.time() - 1
    update.atomic(pc.ROOT / 'plan.json', plan)
    with pytest.raises(ValueError, match='expired'):
        pc.action('install', {'confirm': True, 'plan_id': plan['id']})
    assert calls == []


def test_install_downloads_backs_up_and_pins_exact_versions(system):
    plan, calls = system
    result = pc.action('install', {'confirm': True, 'plan_id': plan['id']})
    assert result['state']['status'] == 'queued_install'
    pc.worker('install')
    assert pc.status()['state']['status'] == 'installed'
    assert pc.status()['reboot_required'] is True
    install = next(c for c in calls if '--no-download' in c)
    download = next(c for c in calls if '--download-only' in c)
    backup = next(c for c in calls if '/opt/airlink/os/recovery/backup.sh' in c)
    assert calls.index(download) < calls.index(backup) < calls.index(install)
    assert 'linux-image-amd64=6.2' in install and '--no-remove' in install
    assert 'APT::Get::AllowUnauthenticated=false' in install


def test_dependency_changes_block_installation(system, monkeypatch):
    plan, calls = system
    pc.action('install', {'confirm': True, 'plan_id': plan['id']})
    monkeypatch.setattr(pc, 'run', lambda command, **kw: 'Inst unexpected (1.0 repo)' if '--simulate' in command else '')
    with pytest.raises(ValueError, match='dependencies changed'):
        pc.worker('install')
    assert pc.status()['state']['status'] == 'rejected'
    assert not pc.status()['state']['recovery_required']


@pytest.mark.parametrize('phase,recovery', [('--download-only', False), ('--no-download', True), ('backup.sh', False)])
def test_failures_before_and_during_install_are_distinguished(system, monkeypatch, phase, recovery):
    plan, calls = system
    pc.action('install', {'confirm': True, 'plan_id': plan['id']})
    original = pc.run
    def fail(command, **kw):
        if any(phase in arg for arg in command):
            raise RuntimeError('Test failure')
        return original(command, **kw)
    monkeypatch.setattr(pc, 'run', fail)
    with pytest.raises(RuntimeError, match='Test failure'):
        pc.worker('install')
    assert pc.status()['state']['recovery_required'] is recovery
    if recovery:
        with pytest.raises(ValueError, match='recovery'):
            pc.action('check', {})
        with pytest.raises(ValueError, match='PC update'):
            update.guard_pc_updates()


def test_app_updates_and_restarts_cannot_overlap(system):
    update.atomic(update.ROOT / 'state.json', {'status': 'queued'})
    with pytest.raises(ValueError, match='application update'):
        pc.action('check', {})
    update.atomic(update.ROOT / 'state.json', {'status': 'idle'})
    pc.action('check', {})
    with pytest.raises(ValueError, match='PC update'):
        update.restart_system({'confirm': True})


def test_interrupted_install_requires_review_and_cannot_be_cleared_by_worker(system):
    pc.write_state('installing')
    state = update.read(pc.ROOT / 'state.json', {})
    state['at'] = time.time() - 60
    update.atomic(pc.ROOT / 'state.json', state)
    assert pc.status()['state']['recovery_required'] is True
    with pytest.raises(ValueError, match='No matching'):
        pc.worker('check')
    assert pc.status()['state']['recovery_required'] is True


def test_unsupported_preview_never_runs_commands(system, monkeypatch):
    monkeypatch.setattr(pc, 'supported', lambda: False)
    assert not pc.status()['supported']
    with pytest.raises(ValueError, match='installed'):
        pc.action('check', {})
    assert system[1] == []


def test_check_offers_vendor_microcode_and_retains_kernel_plan(system, tmp_path, monkeypatch):
    cpu = tmp_path / 'cpuinfo'
    cpu.write_text('vendor_id : GenuineIntel')
    monkeypatch.setattr(pc, 'CPU_INFO', cpu)
    calls = []
    def run(command, **kwargs):
        calls.append(command)
        if command[0] == 'dpkg-query': return ''
        if command[0] == 'apt-cache': return '  Candidate: 3.20261101.1\n'
        if '--simulate' in command:
            base = 'Inst linux-image-amd64 [6.1] (6.2 repo)'
            return base + ('\nInst intel-microcode (3.20261101.1 repo)' if 'install' in command else '')
        return ''
    monkeypatch.setattr(pc, 'run', run)
    pc.action('check', {})
    pc.worker('check')
    assert pc.status()['state']['status'] == 'ready'
    packages = pc.status()['plan']['packages']
    assert {p['category'] for p in packages} == {'CPU microcode', 'Kernel / drivers'}
    assert any('intel-microcode=3.20261101.1' in command for command in calls)


def test_failed_online_check_hides_previous_plan(system, monkeypatch):
    pc.action('check', {})
    monkeypatch.setattr(pc, 'run', lambda *a, **kw: (_ for _ in ()).throw(RuntimeError('Offline')))
    with pytest.raises(RuntimeError, match='Offline'):
        pc.worker('check')
    assert pc.status()['plan'] is None
    assert pc.status()['state']['status'] == 'rejected'
