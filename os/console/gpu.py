"""Read-only PCI GPU detection and optional NVIDIA driver telemetry."""
import csv
import math
import re
import shlex
import shutil
import subprocess
import time
from functools import lru_cache
from pathlib import Path

PCI_ROOT = Path('/sys/bus/pci/devices')
VENDORS = {'0x10de': 'NVIDIA', '0x1002': 'AMD', '0x8086': 'Intel', '0x1234': 'QEMU'}
# PCI 2191 includes laptop Max-Q variants; do not guess the subsystem variant.
KNOWN_NAMES = {('0x10de', '0x2191'): 'NVIDIA GeForce GTX 1660 Ti (laptop)'}
PCI_DATABASES = (Path('/usr/share/misc/pci.ids'), Path('/usr/share/hwdata/pci.ids'),
                 Path('/usr/share/pci.ids'))


def has_model(value):
    """Numeric PCI placeholders and failed driver readings are not model names."""
    value = value.strip()
    return bool(value and value.lower() not in {'n/a', 'unknown', '[not supported]', 'nvidia', 'amd', 'intel'}
                and not re.fullmatch(r'(?:0x)?[0-9a-fA-F]{4}', value)
                and not re.search(r'\bDevice\s+(?:0x)?[0-9a-fA-F]{4}$', value, re.IGNORECASE))


@lru_cache(maxsize=8)
def _pci_models(path, modified, size, wanted):
    """Read only GPU entries; cache by database revision and detected PCI IDs."""
    models = {}
    vendor = None
    vendor_name = ''
    with path.open(errors='replace') as database:
        for line in database:
            if line.startswith(('#', '\n', '\t\t')):
                continue
            if not line.startswith('\t'):
                match = re.match(r'^([0-9a-fA-F]{4})\s+(.+)', line)
                vendor = '0x' + match[1].lower() if match else None
                vendor_name = VENDORS.get(vendor, match[2].strip()) if match else ''
            elif vendor:
                match = re.match(r'^\t([0-9a-fA-F]{4})\s+(.+)', line)
                key = (vendor, '0x' + match[1].lower()) if match else None
                if key in wanted and has_model(match[2]):
                    models[key] = (vendor_name + ' ' + match[2].strip())[:200]
    return models


def pci_model_names(devices):
    wanted = tuple(sorted({(gpu['vendor_id'], gpu['device_id']) for gpu in devices}))
    models = {}
    if not wanted:
        return models
    for path in PCI_DATABASES:
        try:
            info = path.stat()
            if info.st_size > 16 * 1024 * 1024:
                continue
            for key, value in _pci_models(path, info.st_mtime_ns, info.st_size, wanted).items():
                models.setdefault(key, value)
        except OSError:
            continue
    return models


def command(args):
    executable = shutil.which(args[0])
    if not executable:
        return ''
    try:
        result = subprocess.run([executable, *args[1:]], capture_output=True,
                                text=True, timeout=3, check=False)
        return result.stdout if result.returncode == 0 else ''
    except (OSError, subprocess.TimeoutExpired):
        return ''


def address(value):
    value = value.strip().lower()
    if not re.fullmatch(r'[0-9a-f]{4,8}:[0-9a-f]{2}:[0-9a-f]{2}\.[0-7]', value):
        return None
    domain, bus, slot = value.split(':')
    return f'{int(domain, 16):04x}:{bus}:{slot}'


def number(value):
    try:
        result = float(value.strip())
        return result if math.isfinite(result) and result >= 0 else None
    except (ValueError, AttributeError):
        return None


def device_names():
    names = {}
    for line in command(['lspci', '-D', '-mm']).splitlines():
        try:
            row = shlex.split(line)
            if len(row) >= 4 and address(row[0]) and has_model(row[3]):
                names[address(row[0])] = (row[2] + ' ' + row[3])[:200]
        except ValueError:
            continue
    return names


def detect(pci_root=None, name_lookup=None):
    root = PCI_ROOT if pci_root is None else Path(pci_root)
    devices = []
    for path in sorted(root.glob('*')):
        try:
            if int((path / 'class').read_text().strip(), 16) >> 16 != 0x03:
                continue
            vendor_id = (path / 'vendor').read_text().strip().lower()
            device_id = (path / 'device').read_text().strip().lower()
            bus = address(path.name)
            if bus is None:
                continue
            driver = (path / 'driver').resolve().name if (path / 'driver').is_symlink() else None
        except (OSError, ValueError):
            continue
        vendor = VENDORS.get(vendor_id, vendor_id)
        devices.append({'pci_address': bus, 'vendor': vendor, 'vendor_id': vendor_id,
                        'device_id': device_id, 'name': KNOWN_NAMES.get((vendor_id, device_id), f'{vendor} {device_id}'),
                        'driver': driver, 'status': 'loaded' if driver else 'not_loaded',
                        'driver_version': None, 'memory_total_mib': None,
                        'memory_used_mib': None, 'utilization_percent': None, 'temperature_c': None})
    if not devices:
        return []
    names = (name_lookup or device_names)()
    unresolved = [gpu for gpu in devices if not has_model(names.get(gpu['pci_address'], ''))]
    models = pci_model_names(unresolved)
    for gpu in devices:
        name = names.get(gpu['pci_address'], '')
        gpu['name'] = (name[:200] if has_model(name) else
                       models.get((gpu['vendor_id'], gpu['device_id']), gpu['name']))
    if any(gpu['vendor_id'] == '0x10de' for gpu in devices):
        output = command(['nvidia-smi',
            '--query-gpu=pci.bus_id,name,driver_version,memory.total,memory.used,utilization.gpu,temperature.gpu',
            '--format=csv,noheader,nounits'])
        readings = {}
        for row in csv.reader(output.splitlines()):
            if len(row) == 7 and address(row[0]):
                readings[address(row[0])] = row
        for gpu in devices:
            row = readings.get(gpu['pci_address'])
            if gpu['vendor_id'] != '0x10de' or row is None or gpu['driver'] != 'nvidia':
                continue
            gpu.update(name=row[1].strip()[:200] if has_model(row[1]) else gpu['name'],
                       driver_version=row[2].strip()[:80],
                       status='ready', memory_total_mib=number(row[3]),
                       memory_used_mib=number(row[4]), utilization_percent=number(row[5]),
                       temperature_c=number(row[6]))
    return devices


class Sampler:
    """Cache PCI display names, not driver state or live utilization readings."""
    def __init__(self, pci_root=None):
        self.pci_root = pci_root
        self.names = {}
        self.names_at = None

    def read(self):
        def lookup():
            stamp = time.monotonic()
            if self.names_at is None or stamp - self.names_at >= 60:
                self.names = device_names()
                self.names_at = stamp
            return self.names
        return detect(self.pci_root, name_lookup=lookup)


if __name__ == '__main__':
    import json
    print(json.dumps(detect(), indent=2))
