"""Bounded, shared host performance sampling; dashboard requests never run probes."""
import copy
import importlib.util
import logging
import platform
import socket
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import psutil
from .connection_latency import service as latency_service

log = logging.getLogger(__name__)


def optional(function, default=None):
    try:
        return function()
    except (OSError, ValueError, RuntimeError, NotImplementedError, AttributeError, psutil.Error):
        return default


def rate(current, previous, elapsed):
    if current is None or previous is None or elapsed <= 0 or current < previous:
        return None
    return (current - previous) / elapsed


def gpu_readings():
    # Reuse the installed console's PCI/NVIDIA detector without importing its root broker.
    path = Path(__file__).resolve().parents[2] / 'os' / 'console' / 'gpu.py'
    spec = importlib.util.spec_from_file_location('airlink_host_gpu', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.detect()


def ethernet_ports(names):
    if sys.platform == 'darwin':
        try:
            output = subprocess.run(['/usr/sbin/networksetup', '-listallhardwareports'],
                capture_output=True, text=True, timeout=2, check=True).stdout
            ports = set()
            hardware = ''
            for line in output.splitlines():
                if line.startswith('Hardware Port:'):
                    hardware = line.split(':', 1)[1].strip().lower()
                elif line.startswith('Device:') and 'ethernet' in hardware:
                    ports.add(line.split(':', 1)[1].strip())
            return ports
        except (OSError, subprocess.SubprocessError):
            return set()
    ports = set()
    for name in names:
        path = Path('/sys/class/net') / name
        try:
            if (path.joinpath('type').read_text().strip() == '1' and
                    not path.joinpath('wireless').exists() and
                    path.joinpath('device').exists() and '/virtual/' not in str(path.resolve())):
                ports.add(name)
        except OSError:
            continue
    return ports


class SystemStats:
    def __init__(self):
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.thread = None
        self.previous = None
        self.snapshot = {'status': 'collecting'}
        self.sampled_at = None

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.previous = None
        latency_service.start()
        self.stop_event.clear()
        self.thread = threading.Thread(target=self.run, name='airlink-host-stats', daemon=True)
        self.thread.start()

    def stop(self):
        latency_service.stop()
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=8)

    def read(self):
        with self.lock:
            result = copy.deepcopy(self.snapshot)
            if self.sampled_at is not None and time.monotonic() - self.sampled_at > 30:
                return {'status': 'stale'}
            result['latency'] = latency_service.read()
            return result

    def sample(self):
        stamp = time.monotonic()
        cpu = optional(lambda: psutil.cpu_percent(interval=None))
        memory = optional(psutil.virtual_memory)
        disk = optional(psutil.disk_io_counters)
        network = optional(lambda: psutil.net_io_counters(pernic=True), {})
        stats = optional(psutil.net_if_stats, {})
        frequency = optional(psutil.cpu_freq)
        storage = optional(lambda: psutil.disk_usage('/'))
        previous = self.previous
        elapsed = stamp - previous['stamp'] if previous else 0
        interfaces = []
        ethernet = ethernet_ports(network)
        for name, counters in network.items():
            state = stats.get(name)
            if not state or name in ('lo', 'lo0') or 'loopback' in getattr(state, 'flags', ''):
                continue
            before = previous['network'].get(name) if previous and state.isup else None
            interfaces.append({'name': name, 'kind': 'ethernet' if name in ethernet else 'other',
                'is_up': bool(state.isup), 'link_mbps': state.speed if state.speed > 0 else None,
                'rx_bytes_sec': rate(counters.bytes_recv, before.bytes_recv if before else None, elapsed),
                'tx_bytes_sec': rate(counters.bytes_sent, before.bytes_sent if before else None, elapsed)})
        old_disk = previous['disk'] if previous else None
        gpus = optional(gpu_readings)
        data = {'status': 'ready', 'hostname': socket.gethostname(), 'platform': platform.system(),
            'observed_at': datetime.now(timezone.utc).isoformat(),
            'cpu_percent': cpu if previous else None,
            'cpu_mhz': frequency.current if frequency and frequency.current > 0 else None,
            'cpu_threads': optional(psutil.cpu_count),
            'cpu_cores': optional(lambda: psutil.cpu_count(logical=False)),
            'memory': {'total_bytes': memory.total, 'used_bytes': memory.used,
                       'available_bytes': memory.available, 'percent': memory.percent} if memory else None,
            'storage': {'total_bytes': storage.total, 'used_bytes': storage.used,
                        'free_bytes': storage.free, 'percent': storage.percent} if storage else None,
            'disk_read_bytes_sec': rate(disk.read_bytes if disk else None, old_disk.read_bytes if old_disk else None, elapsed),
            'disk_write_bytes_sec': rate(disk.write_bytes if disk else None, old_disk.write_bytes if old_disk else None, elapsed),
            'network': interfaces, 'gpus': gpus,
            'uptime_seconds': optional(lambda: max(0, time.time() - psutil.boot_time()))}
        self.previous = {'stamp': stamp, 'disk': disk, 'network': network}
        with self.lock:
            self.snapshot = data
            self.sampled_at = time.monotonic()

    def run(self):
        while not self.stop_event.is_set():
            try:
                self.sample()
            except Exception:
                log.exception('Host performance sampling failed')
            self.stop_event.wait(3)


service = SystemStats()
