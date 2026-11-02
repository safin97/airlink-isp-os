"""Bounded ICMP discovery of a tower's management subnet."""
import ipaddress
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor


def management_network(address, prefix):
    if not address:
        raise ValueError('Set the tower management IP before discovering devices')
    ip = ipaddress.ip_address(address)
    if ip.version != 4:
        raise ValueError('Subnet discovery currently requires an IPv4 management IP')
    if not 24 <= prefix <= 32:
        raise ValueError('Choose a prefix from /24 to /32 (at most 254 hosts)')
    return ipaddress.ip_network(f'{ip}/{prefix}', strict=False)


def ping_host(executable, address):
    # macOS uses milliseconds for -W; Linux uses seconds. Never invoke a shell.
    wait = '1000' if sys.platform == 'darwin' else '1'
    result = subprocess.run([executable, '-n', '-c', '1', '-W', wait, address],
                            capture_output=True, timeout=3, check=False)
    if result.returncode not in (0, 1, 2):
        raise RuntimeError('Ping is unavailable or not permitted on this server')
    error_code = 1 if sys.platform == 'darwin' else 2
    if result.returncode == error_code:
        raise RuntimeError('Ping could not run; check server network and ICMP permissions')
    return result.returncode == 0


def scan(network):
    executable = shutil.which('ping')
    if not executable:
        raise RuntimeError('Ping is not installed on the AirLink server')
    addresses = [str(host) for host in network.hosts()]
    def probe(address):
        try:
            return ping_host(executable, address)
        except subprocess.TimeoutExpired:
            return False
    with ThreadPoolExecutor(max_workers=32) as pool:
        results = list(pool.map(probe, addresses))
    return [address for address, reachable in zip(addresses, results) if reachable]
