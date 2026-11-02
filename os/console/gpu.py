"""Read-only PCI GPU detection and optional NVIDIA driver telemetry."""
import csv
import math
import re
import shlex
import shutil
import subprocess
from pathlib import Path

PCI_ROOT = Path('/sys/bus/pci/devices')
VENDORS = {'0x10de': 'NVIDIA', '0x1002': 'AMD', '0x8086': 'Intel', '0x1234': 'QEMU'}


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


def detect(pci_root=None):
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
                        'device_id': device_id, 'name': f'{vendor} {device_id}',
                        'driver': driver, 'status': 'loaded' if driver else 'not_loaded',
                        'driver_version': None, 'memory_total_mib': None,
                        'memory_used_mib': None, 'utilization_percent': None, 'temperature_c': None})
    if not devices:
        return []
    names = {}
    for line in command(['lspci', '-D', '-mm']).splitlines():
        try:
            row = shlex.split(line)
            if len(row) >= 4 and address(row[0]):
                names[address(row[0])] = (row[2] + ' ' + row[3])[:200]
        except ValueError:
            continue
    for gpu in devices:
        gpu['name'] = names.get(gpu['pci_address'], gpu['name'])
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
            gpu.update(name=row[1].strip()[:200], driver_version=row[2].strip()[:80],
                       status='ready', memory_total_mib=number(row[3]),
                       memory_used_mib=number(row[4]), utilization_percent=number(row[5]),
                       temperature_c=number(row[6]))
    return devices


if __name__ == '__main__':
    import json
    print(json.dumps(detect(), indent=2))
