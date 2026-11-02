"""Shared bounded ICMP probes; HTTP/WebSocket requests only read cached results."""
import copy
import os
import re
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

TARGETS = {'google_dns': '8.8.8.8', 'gaming': '1.1.1.1'}


def measure(target):
    result = {'target': target, 'rtt_ms': None, 'status': 'unavailable',
              'observed_at': datetime.now(timezone.utc).isoformat()}
    try:
        process = subprocess.run(['ping', '-n', '-c', '1', '-W',
            '2000' if sys.platform == 'darwin' else '2', target],
            capture_output=True, text=True, timeout=3,
            env={**os.environ, 'LC_ALL': 'C'})
        match = re.search(r'\btime\s*([=<])\s*(\d+(?:\.\d+)?)\s*ms', process.stdout)
        if process.returncode == 0 and match:
            result.update(rtt_ms=float(match[2]), less_than=match[1] == '<', status='ready')
        else:
            result['status'] = 'no_reply'
    except subprocess.TimeoutExpired:
        result['status'] = 'no_reply'
    except (OSError, ValueError):
        pass
    return result


class ConnectionLatency:
    def __init__(self):
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.thread = None
        self.sampled_at = None
        self.results = {}

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.stop_event.clear()
        self.thread = threading.Thread(target=self.run, name='airlink-connection-latency', daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=4)

    def read(self):
        with self.lock:
            data = copy.deepcopy(self.results)
            if self.sampled_at is not None and time.monotonic() - self.sampled_at > 15:
                return {key: {'target': host, 'rtt_ms': None, 'status': 'stale'} for key, host in TARGETS.items()}
            return data

    def run(self):
        with ThreadPoolExecutor(max_workers=2, thread_name_prefix='airlink-ping') as pool:
            while not self.stop_event.is_set():
                started = time.monotonic()
                readings = dict(zip(TARGETS, pool.map(measure, TARGETS.values())))
                with self.lock:
                    self.results = readings
                    self.sampled_at = time.monotonic()
                self.stop_event.wait(max(0, 5 - (time.monotonic() - started)))


service = ConnectionLatency()
