"""Bounded public wireless registration fields; never expose raw device records."""
import re
from .client_telemetry import number


def mac_address(value):
    if not isinstance(value, str):
        return None
    raw = value.replace(':', '').replace('-', '')
    if not re.fullmatch(r'[0-9a-fA-F]{12}', raw):
        return None
    return ':'.join(raw[i:i+2] for i in range(0, 12, 2)).upper()


def public_clients(rows):
    result = []
    if not isinstance(rows, list):
        return result
    for row in rows[:256]:
        if not isinstance(row, dict):
            continue
        mac = mac_address(row.get('mac_address'))
        if not mac:
            continue
        result.append({'mac_address': mac,
            'interface': str(row.get('interface') or '')[:120],
            'ssid': str(row.get('ssid') or '')[:128],
            'signal_dbm': row.get('signal_dbm') if number(row.get('signal_dbm'), -150, -.001) else None})
    return result


def ssids(values):
    return sorted({value[:128] for value in values if isinstance(value, str) and value})[:32]
