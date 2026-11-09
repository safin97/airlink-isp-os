"""Sequential, bounded login selection for one already verified online session."""
import asyncio
import httpx
from . import device_management, routeros_native
from .vendor_identity import VENDOR_LABELS


def candidates(config, vendor):
    def candidate(kind, protocol=None):
        # A custom web port must never be mistaken for a native API or SSH port.
        result = {**config, 'transport': kind, 'vendor_hint': vendor}
        if kind != 'web':
            result['port'] = None
        if protocol:
            result['protocol'] = protocol
        return result
    web = [candidate('web', scheme) for scheme in ('https', 'http')
           if config.get('protocol', 'both') in ('both', scheme)]
    native = [candidate('routeros_tls'), candidate('routeros')]
    ssh = candidate('airos_ssh')
    if vendor.startswith('ubiquiti'):
        return [ssh, *web]
    if vendor == 'mikrotik':
        return [*web[:1], native[0], *web[1:], native[1]]
    return [*web, *native] + ([] if config.get('background') else [ssh])


async def detect_and_connect(address, config, transport=None):
    from .online_device import collect_once, with_connection
    vendor = 'generic'
    metadata = {'detected_vendor': vendor, 'device_type': VENDOR_LABELS[vendor], 'detection_source': 'Device API'}
    attempts, trust, rejected = [], None, False
    options = candidates(config, vendor)
    # A trusted SSH key means the user explicitly requested the SSH settings connection.
    if config.get('ssh_fingerprint') and vendor != 'mikrotik':
        options.sort(key=lambda c: c['transport'] != 'airos_ssh')
    for option in options:
        label = {'routeros_tls': 'RouterOS API-SSL', 'routeros': 'RouterOS API', 'airos_ssh': 'Ubiquiti SSH'}.get(
            option['transport'], option.get('protocol', 'https').upper() + ' web API')
        try:
            result = await asyncio.wait_for(collect_once(address, option, transport),
                                            timeout=25 if option['transport'] == 'airos_ssh' else 12)
            if result.get('requires_trust'):
                trust = with_connection(result, option)
                attempts.append({'connection': label, 'status': 'SSH key verification required'})
                continue
            attempts.append({'connection': label, 'status': 'Connected'})
            if vendor == 'generic':
                metadata['detected_vendor'] = ('mikrotik' if result.get('vendor') == 'MikroTik'
                                                else result.get('detected_vendor', 'ubiquiti'))
                metadata['device_type'] = VENDOR_LABELS[metadata['detected_vendor']]
            result = {**with_connection(result, option), **metadata, 'connection_attempts': attempts}
            if trust and result.get('vendor') == 'Ubiquiti':
                result['ssh_upgrade_fingerprint'] = trust['ssh_fingerprint']
            return result
        except PermissionError:
            rejected = True
            attempts.append({'connection': label, 'status': 'Login rejected'})
        except device_management.ManagementError as exc:
            if exc.status == 409:  # Never bypass a changed SSH host key.
                raise
            attempts.append({'connection': label, 'status': 'Unavailable'})
        except (OSError, EOFError, httpx.HTTPError, ValueError, RuntimeError, routeros_native.APIError, asyncio.TimeoutError):
            attempts.append({'connection': label, 'status': 'Unavailable'})
    if trust:
        return {**trust, **metadata, 'connection_attempts': attempts}
    if rejected:
        raise PermissionError('Device login rejected')
    raise RuntimeError('Automatic connection failed. Check the device username/password and enable its web, RouterOS API, or airOS SSH service.')
