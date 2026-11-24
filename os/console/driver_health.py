"""Read-only Linux driver inventory. Binding is not a performance benchmark."""
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
import platform
import shlex
import subprocess
import time

# Keep the inventory and warning summaries below the control socket's 1 MiB limit.
LIMIT = 512
PCI_CLASSES = {1: 'Storage', 2: 'Network', 3: 'Graphics', 4: 'Audio / video',
               6: 'Bridge', 12: 'Serial / USB controller'}


def read(path):
    try:
        with path.open() as stream:
            return stream.read(256).strip()
    except (OSError, UnicodeError):
        return ''


def entries(path):
    try:
        return sorted(path.iterdir())
    except OSError:
        return []


def link_name(path):
    try:
        return path.resolve(strict=True).name if path.is_symlink() else None
    except OSError:
        return None


def pci_names():
    try:
        result = subprocess.run(['lspci', '-D', '-mm'], capture_output=True,
                                text=True, timeout=2, check=False)
        if result.returncode:
            return {}
        names = {}
        for line in result.stdout.splitlines():
            try:
                row = shlex.split(line)
                if len(row) >= 4:
                    names[row[0]] = (row[2] + ' ' + row[3])[:200]
            except ValueError:
                continue
        return names
    except (OSError, subprocess.TimeoutExpired):
        return {}


def collect(gpus=(), sys_root=Path('/sys')):
    stamp = datetime.now(timezone.utc).isoformat()
    root = Path(sys_root)
    result = {'status': 'unavailable', 'checked_at': stamp, 'kernel': platform.release(),
              'devices': [], 'modules': [], 'counts': {}, 'truncated': False,
              'note': 'Driver checks require the installed AirLink Linux PC and readable sysfs.'}
    buses = entries(root / 'bus')
    if not buses:
        return result
    deadline = time.monotonic() + 6
    names = pci_names()
    gpu_by_id = {g['pci_address']: g for g in (gpus or ()) if g.get('pci_address')}
    devices = result['devices']
    for bus in buses:
        for path in entries(bus / 'devices'):
            if len(devices) >= LIMIT or time.monotonic() > deadline:
                result['truncated'] = True
                break
            driver = link_name(path / 'driver')
            module = link_name(path / 'driver' / 'module')
            state = 'loaded' if driver else 'unknown'
            detail = 'Driver bound to this device; performance is not benchmarked.' if driver else (
                'No driver binding reported. Some devices are managed by a parent or built into the kernel.')
            category = bus.name.upper()
            name = path.name
            if bus.name == 'pci':
                try:
                    pci_class = int(read(path / 'class'), 16) >> 16
                except ValueError:
                    pci_class = -1
                category = PCI_CLASSES.get(pci_class, 'PCI device')
                name = names.get(path.name, f'{category} {read(path / "vendor")}:{read(path / "device")}')
                if not driver and pci_class in (1, 2, 3):
                    state, detail = 'warning', 'No driver bound. Check whether this device is intentionally unused or needs a driver.'
            elif bus.name == 'usb':
                name = read(path / 'product') or read(path / 'interface') or path.name
            if bus.name == 'usb' and read(path / 'authorized') == '0':
                state, detail = 'warning', 'USB device is not authorized by the operating system.'
            if module and read(root / 'module' / module / 'initstate') in ('coming', 'going'):
                state, detail = 'warning', 'Driver module is loading or unloading. Refresh to check again.'
            gpu = gpu_by_id.get(path.name, {}) if bus.name == 'pci' else {}
            if gpu.get('name'):
                name = gpu['name']
            metrics = []
            if driver == 'nvidia' and gpu.get('status') != 'ready':
                state, detail = 'unknown', 'NVIDIA driver is bound, but telemetry is unavailable. Graphics performance is unverified.'
            for key, label, unit in [('utilization_percent', 'GPU usage', '%'),
                                     ('temperature_c', 'Temperature', ' °C'),
                                     ('memory_used_mib', 'VRAM used', ' MiB')]:
                if gpu.get(key) is not None:
                    metrics.append(f'{label}: {gpu[key]:g}{unit}')
            devices.append({'id': f'{bus.name}/{path.name}', 'name': name[:200], 'category': category,
                            'bus': bus.name, 'driver': driver, 'module': module,
                            'version': gpu.get('driver_version') or (read(root / 'module' / module / 'version') if module else '') or None,
                            'status': state, 'detail': detail, 'metrics': metrics})
        if result['truncated']:
            break
    # CPU frequency scaling is a kernel policy, not a PCI device driver.
    policies = entries(root / 'devices/system/cpu/cpufreq')[:LIMIT]
    scaling = sorted({read(p / 'scaling_driver') for p in policies} - {''})
    governors = sorted({read(p / 'scaling_governor') for p in policies} - {''})
    microcode = read(root / 'devices/system/cpu/cpu0/microcode/version')
    devices.append({'id': 'cpu/power-management', 'name': 'CPU power management', 'category': 'CPU',
                    'bus': 'cpu', 'driver': ', '.join(scaling) or None, 'module': None, 'version': None,
                    'status': 'loaded' if scaling else 'unknown',
                    'detail': 'CPU scaling driver active.' if scaling else 'CPU scaling driver not exposed; this is common in virtual machines.',
                    'metrics': ([f'Governor: {", ".join(governors)}'] if governors else []) +
                               ([f'CPU 0 microcode: {microcode}'] if microcode else [])})
    module_paths = entries(root / 'module')
    for path in module_paths[:LIMIT]:
        if time.monotonic() > deadline:
            result['truncated'] = True
            break
        state = read(path / 'initstate')
        result['modules'].append({'name': path.name, 'version': read(path / 'version') or None,
                                  'status': 'warning' if state in ('coming', 'going') else 'loaded',
                                  'detail': f'Module state: {state}' if state else 'Kernel component; separate module state not exposed.'})
    if len(module_paths) > LIMIT:
        result['truncated'] = True
    counts = Counter(d['status'] for d in devices)
    result.update(status='partial' if result['truncated'] else 'ready',
                  counts={state: counts[state] for state in ('loaded', 'warning', 'unknown')},
                  note='Device bindings and loaded kernel components, including built-in drivers. Loaded does not prove optimal performance or that a driver is up to date.')
    devices.sort(key=lambda d: ({'warning': 0, 'unknown': 1, 'loaded': 2}[d['status']], d['category'], d['name']))
    return result
