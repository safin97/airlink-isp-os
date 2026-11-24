"""Owner-reviewed updates from the appliance's existing APT repositories."""
import fcntl
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from contextlib import contextmanager, nullcontext
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from updates import update
from updates import gpu_driver

ROOT = Path('/var/lib/airlink-system/pc-updates')
INSTALLED = Path('/etc/airlink/installed')
DPKG_STATUS = Path('/var/lib/dpkg/status')
CPU_INFO = Path('/proc/cpuinfo')
BUSY = {'queued_check', 'checking', 'queued_install', 'installing'}
UNITS = {'check': 'airlink-pc-update-check.service', 'install': 'airlink-pc-update-install.service'}
APT = ['apt-get', '-o', 'APT::Get::AllowUnauthenticated=false',
       '-o', 'Acquire::AllowInsecureRepositories=false',
       '-o', 'Acquire::AllowDowngradeToInsecureRepositories=false',
       '-o', 'APT::Update::Error-Mode=any', '-o', 'Acquire::Retries=2',
       '-o', 'Acquire::http::Timeout=30', '-o', 'Acquire::https::Timeout=30',
       '-o', 'Dpkg::Options::=--force-confdef', '-o', 'Dpkg::Options::=--force-confold']
NAME = r'[a-z0-9][a-z0-9+.-]*(?::[a-z0-9]+)?'
VERSION = r'[0-9][A-Za-z0-9.+:~\-]*'
INSTALL_LINE = re.compile(r'^Inst (' + NAME + r')(?: \[([^\]]+)\])? \((' + VERSION + r')(?:\s|\))')


def supported():
    return sys.platform == 'linux' and INSTALLED.exists() and shutil.which('apt-get') is not None


def run(command, timeout=300, ok=(0,)):
    result = subprocess.run(command, capture_output=True, text=True, timeout=timeout,
                            env={**os.environ, 'LC_ALL': 'C', 'DEBIAN_FRONTEND': 'noninteractive',
                                 'NEEDRESTART_MODE': 'l'})
    if result.returncode not in ok:
        detail = re.sub(r'(https?://)[^\s/@]+(?::[^\s/@]*)?@', r'\1[redacted]@', result.stderr[-4000:])
        detail = re.sub(r'(?i)(token|password|secret|authorization)([=: ]+)[^\s&;]+', r'\1\2[redacted]', detail)
        if detail:
            print(detail, file=sys.stderr, flush=True)
        raise RuntimeError('Package operation failed. Check internet access, repository configuration, '
                           'free disk space and the local PC update service journal.')
    return result.stdout


def category(name):
    name = name.split(':')[0]
    if name in {'intel-microcode', 'amd64-microcode'}:
        return 'CPU microcode'
    if name.startswith(('nvidia', 'libnvidia', 'cuda', 'libcuda')) or 'mesa' in name or name.startswith('xserver-xorg-video'):
        return 'GPU driver'
    if name.startswith('firmware-'):
        return 'Device firmware'
    if name.startswith(('linux-', 'dkms')):
        return 'Kernel / drivers'
    return 'System package'


def parse_plan(output):
    packages = []
    for line in output.splitlines():
        if line.startswith(('Remv ', 'Purg ')):
            raise ValueError('This update would remove packages. Local maintenance is required.')
        if not line.startswith('Inst '):
            continue
        match = INSTALL_LINE.match(line)
        if not match:
            raise ValueError('Cannot read the package plan. No updates were installed.')
        name, previous, version = match.groups()
        if name.split(':')[0] == 'airlink-isp-os':
            raise ValueError('Update AirLink itself through Software Updates before checking PC updates.')
        if previous:
            # Never turn an approved upgrade into a downgrade.
            result = subprocess.run(['dpkg', '--compare-versions', version, 'ge', previous], capture_output=True)
            if result.returncode:
                raise ValueError('Package downgrades require local maintenance.')
        packages.append({'name': name, 'installed': previous, 'candidate': version, 'category': category(name)})
    if len(packages) > 2000 or len({p['name'] for p in packages}) != len(packages):
        raise ValueError('Unexpected package plan. Review the appliance locally.')
    return sorted(packages, key=lambda p: p['name'])


def specifications(packages):
    return [p['name'] + '=' + p['candidate'] for p in packages]


def fingerprint():
    return hashlib.sha256(DPKG_STATUS.read_bytes()).hexdigest()


def boot_id():
    try:
        return Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    except OSError:
        return None


def write_state(status, **fields):
    update.atomic(ROOT / 'state.json', {'status': status, 'at': time.time(), 'boot_id': boot_id(), **fields})


def reconcile(locked=False):
    state = update.read(ROOT / 'state.json', {'status': 'idle'})
    if state['status'] in BUSY and time.time() - state.get('at', 0) > 30:
        try:
            with nullcontext() if locked else maintenance_lock():
                current = update.read(ROOT / 'state.json', {})
                if current != state:
                    return current
                unit = UNITS['install' if 'install' in state['status'] else 'check']
                active = run(['systemctl', 'is-active', unit], ok=(0, 3, 4)).strip()
                if state.get('boot_id') != boot_id() or active not in {'active', 'activating', 'reloading'}:
                    installing = state['status'] == 'installing'
                    write_state('failed' if installing else 'rejected', recovery_required=installing,
                                error='PC update job was interrupted. Review locally before retrying.' if installing
                                else 'PC update check or queued job was interrupted. Check again.')
                    state = update.read(ROOT / 'state.json', {})
        except ValueError:
            pass  # A worker owns the shared lock; its current state remains authoritative.
    return state


def status():
    available = supported()
    state = reconcile() if available else {'status': 'unavailable'}
    plan = update.read(ROOT / 'plan.json', None) if available and state['status'] == 'ready' else None
    installed = update.read(ROOT / 'installed.json', {}) if available else {}
    reboot = bool(available and (Path('/var/run/reboot-required').exists() or
                  (installed.get('reboot_required') and installed.get('boot_id') == boot_id())))
    return {'supported': available, 'state': state, 'plan': plan, 'reboot_required': reboot,
            'gpu_message': installed.get('gpu_message'),
            'reason': None if available else 'PC updates run on the installed AirLink Linux PC. They are unavailable in the local preview.'}


@contextmanager
def maintenance_lock(blocking=False):
    update.ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
    with open(update.ROOT / 'lock', 'a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        except BlockingIOError:
            raise ValueError('Another update operation is active. Try again when it finishes.') from None
        yield


def check_other_maintenance():
    if update.read(update.ROOT / 'state.json', {}).get('status') in {'queued', 'installing', 'failed'}:
        raise ValueError('Finish or recover the AirLink application update first.')
    if update.restart_status()['pending']:
        raise ValueError('A system restart is pending. Wait for the PC to return.')


def action(name, payload):
    if name == 'status':
        return status()
    if name not in UNITS or not supported():
        raise ValueError('PC updates are available only on the installed AirLink Linux PC.')
    ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
    with maintenance_lock():
        check_other_maintenance()
        state = reconcile(locked=True)
        if state['status'] in BUSY or state.get('recovery_required'):
            raise ValueError('A PC update is active or requires local recovery review.')
        if name == 'install':
            plan = update.read(ROOT / 'plan.json', {})
            if payload.get('confirm') is not True:
                raise ValueError('Review and confirm the PC updates first.')
            if state['status'] != 'ready' or payload.get('plan_id') != plan.get('id') or not plan.get('packages'):
                raise ValueError('The reviewed updates changed. Check again.')
            if time.time() > plan['expires'] or fingerprint() != plan['fingerprint']:
                raise ValueError('The update plan expired or installed packages changed. Check again.')
            update.atomic(ROOT / 'request.json', {'plan_id': plan['id']})
        write_state('queued_' + name)
        try:
            run(['systemctl', 'start', '--no-block', UNITS[name]], timeout=15)
        except Exception:
            update.atomic(ROOT / 'state.json', state)
            raise
    return status()


def create_plan():
    run(APT + ['update'], timeout=900)
    packages = parse_plan(run(APT + ['--simulate', '--no-remove', '--with-new-pkgs', 'upgrade']))
    targets = specifications(packages)
    cpu = CPU_INFO.read_text() if CPU_INFO.exists() else ''
    microcode = 'intel-microcode' if 'GenuineIntel' in cpu else 'amd64-microcode' if 'AuthenticAMD' in cpu else None
    if microcode:
        installed = run(['dpkg-query', '-W', '-f=${db:Status-Status}', microcode], ok=(0, 1)).strip()
        if installed != 'installed':
            candidate = re.search(r'^\s*Candidate: (' + VERSION + r')\s*$',
                                  run(['apt-cache', 'policy', microcode]), re.MULTILINE)
            if candidate:
                targets.append(microcode + '=' + candidate.group(1))
    gpu = gpu_driver.missing_driver_plan(run)
    if gpu:
        # Merge by package name: a requested driver must have one exact version.
        targets = list({spec.split('=', 1)[0]: spec for spec in [*targets, *gpu['targets']]}.values())
    if targets:
        packages = parse_plan(run(APT + ['--simulate', '--no-remove', 'install', *targets]))
    plan = {'packages': packages, 'fingerprint': fingerprint(), 'checked_at': time.time(),
            'expires': time.time() + 3600, 'gpu': gpu}
    plan['id'] = hashlib.sha256(update.canonical(plan)).hexdigest()
    update.atomic(ROOT / 'plan.json', plan)
    write_state('ready')


def install_plan():
    plan = update.read(ROOT / 'plan.json', {})
    request = update.read(ROOT / 'request.json', {})
    if (not plan.get('packages') or request.get('plan_id') != plan.get('id') or
            time.time() > plan['expires'] or fingerprint() != plan['fingerprint']):
        raise ValueError('Approved updates expired or installed packages changed. Check again.')
    gpu = plan.get('gpu') or {}
    if gpu.get('kernel') and gpu_driver.platform.release() != gpu['kernel']:
        raise ValueError('The running kernel changed. Check and review the NVIDIA driver plan again.')
    targets = specifications(plan['packages'])
    command = APT + ['--no-remove', 'install', *targets]
    if parse_plan(run(command + ['--simulate'])) != plan['packages']:
        raise ValueError('Package dependencies changed. Check and review updates again.')
    if shutil.disk_usage('/').free < 3 * 1024**3 or shutil.disk_usage('/boot').free < 256 * 1024**2:
        raise ValueError('Free at least 3 GiB on the system disk and 256 MiB in /boot before updating.')
    if run(['dpkg', '--audit']).strip():
        raise ValueError('Unfinished package configuration requires local maintenance first.')
    update.health_check()
    run(command + ['--download-only', '--assume-yes'], timeout=3600)
    # The existing backup preserves AirLink data/configuration; it is not OS rollback.
    run(['/bin/bash', '/opt/airlink/os/recovery/backup.sh'], timeout=600)
    if fingerprint() != plan['fingerprint'] or parse_plan(run(command + ['--simulate'])) != plan['packages']:
        raise ValueError('Package state changed before installation. Check again.')
    write_state('installing', count=len(plan['packages']))
    run(command + ['--no-download', '--assume-yes'], timeout=5400)
    if run(['dpkg', '--audit']).strip():
        raise RuntimeError('Package configuration is incomplete; review the PC update journal locally.')
    if gpu.get('kernel') and not run(['modinfo', '-k', gpu['kernel'], '-F', 'version', 'nvidia']).strip():
        raise RuntimeError('NVIDIA kernel module was not built. Review the PC update journal and DKMS locally before restarting.')
    # Restart activates updated kernels/drivers and libraries held by running services.
    reboot = bool(plan['packages'])
    update.atomic(ROOT / 'installed.json', {'boot_id': boot_id(), 'reboot_required': reboot, 'plan_id': plan['id'],
        'gpu_message': ('NVIDIA driver packages installed. After restarting, verify driver status and Local display in PC settings → Overview.'
                        if gpu.get('kernel') else None)})
    update.health_check()
    write_state('installed', count=len(plan['packages']))


def worker(name):
    if name not in UNITS or not supported() or os.geteuid() != 0:
        raise ValueError('PC update jobs require the installed Linux appliance and root.')
    with maintenance_lock(blocking=True):
        state = update.read(ROOT / 'state.json', {})
        if state.get('status') != 'queued_' + name:
            raise ValueError('No matching queued PC update request.')
        try:
            check_other_maintenance()
            if name == 'check':
                write_state('checking')
                create_plan()
            else:
                install_plan()
        except Exception as exc:
            recovery = update.read(ROOT / 'state.json', {}).get('status') == 'installing'
            write_state('failed' if recovery else 'rejected', recovery_required=recovery,
                        error=str(exc) if isinstance(exc, (ValueError, RuntimeError)) else 'PC update job failed. Review the service journal locally.')
            raise


if __name__ == '__main__':
    worker(sys.argv[1] if len(sys.argv) == 2 else '')
