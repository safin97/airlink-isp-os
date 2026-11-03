"""airOS 6/8 SSH reads and narrowly scoped SSID saves, with pinned host keys."""
import base64
import hashlib
import json
import re
import socket
import threading
import time
import uuid
import paramiko
from .device_api import airos_values
from .device_management import ManagementError

LIMIT = 1024 * 1024


class TrustRequired(Exception):
    def __init__(self, fingerprint):
        self.fingerprint = fingerprint


class PinnedKey(paramiko.MissingHostKeyPolicy):
    def __init__(self, fingerprint):
        self.fingerprint = fingerprint

    def missing_host_key(self, client, hostname, key):
        fingerprint = 'SHA256:' + base64.b64encode(hashlib.sha256(key.asbytes()).digest()).decode().rstrip('=')
        if not self.fingerprint:
            raise TrustRequired(fingerprint)
        if self.fingerprint != fingerprint:
            raise ManagementError('SSH host key changed. Verify the device before reconnecting.', 409)


def execute(client, command, content=None):
    """Only internal literal commands; never interpolate a user-supplied value."""
    channel = client.get_transport().open_session(timeout=4)
    channel.settimeout(4)
    try:
        channel.exec_command(command)
        if content is not None:
            channel.sendall(content)
        channel.shutdown_write()
        output, errors, deadline = bytearray(), bytearray(), time.monotonic() + 8
        while True:
            if channel.recv_ready():
                output.extend(channel.recv(32768))
            if channel.recv_stderr_ready():
                errors.extend(channel.recv_stderr(32768))
            if len(output) + len(errors) > LIMIT:
                raise ManagementError('Device response is too large.')
            if channel.exit_status_ready() and not channel.recv_ready() and not channel.recv_stderr_ready():
                break
            if time.monotonic() > deadline:
                raise TimeoutError()
            time.sleep(0.01)
        if channel.recv_exit_status() != 0:
            # Remote stderr may include configuration secrets; never return it.
            raise ManagementError('Device command failed. Check SSH permissions and firmware support.')
        return bytes(output)
    finally:
        channel.close()


def settings(raw):
    text = raw.decode('utf-8', errors='strict')
    values = {}
    for line in text.splitlines():
        key, sep, value = line.partition('=')
        if sep:
            if key in values:
                raise ManagementError('Ambiguous device configuration; use its native interface.', 409)
            values[key] = value
    radios = []
    for key, value in values.items():
        match = re.fullmatch(r'wireless\.([1-9][0-9]?)\.ssid', key)
        if match:
            index = int(match[1])
            radios.append({'menu': 'wireless', 'id': '*' + format(index, 'X'),
                'name': values.get('wireless.' + str(index) + '.devname', 'Wireless ' + str(index)),
                'ssid': value, 'editable': True})
    return values, radios


def change_ssid(client, raw, change):
    _, radios = settings(raw)
    radio = next((r for r in radios if r['id'] == change['radio_id'] and r['menu'] == change['menu']), None)
    if not radio or radio['ssid'] != change['previous_ssid']:
        raise ManagementError('SSID changed. Reconnect before saving.', 409)
    if radio['ssid'] == change['ssid']:
        return {'status': 'unchanged'}
    # airOS config is a line-based format. Reject separators in addition to the common SSID validation.
    if any(c in change['ssid'] for c in ('\n', '\r', '\0', '\\')):
        raise ManagementError('This SSID contains characters unsupported by the airOS configuration format.', 422)
    key = 'wireless.' + str(int(radio['id'][1:], 16)) + '.ssid'
    new = ''.join(key + '=' + change['ssid'] + ('\n' if line.endswith('\n') else '')
                  if line.partition('=')[0] == key else line
                  for line in raw.decode().splitlines(keepends=True)).encode()
    # Recheck the entire config so another admin's edits are never overwritten silently.
    if execute(client, 'cat /tmp/system.cfg') != raw:
        raise ManagementError('Device configuration changed. Reconnect before saving.', 409)
    name = '/tmp/airlink-ssid-' + uuid.uuid4().hex + '.cfg'
    execute(client, 'umask 077; cat > ' + name, new)
    try:
        # A firmware-provided tool commits the complete preserved config to flash.
        # No automatic retry after this point: a disconnect may mean the save succeeded.
        execute(client, 'cfgmtd -f ' + name + ' -w')
        execute(client, 'cp ' + name + ' /tmp/system.cfg')
        execute(client, 'rm -f ' + name)
        # The UI explicitly labels this action Save SSID and restart radio.
        execute(client, 'nohup sh -c "sleep 2; reboot" >/dev/null 2>&1 </dev/null &')
    except (ManagementError, OSError, EOFError, paramiko.SSHException):
        raise ManagementError('Save or restart result is unknown. Reconnect and verify before retrying.', 504) from None
    return {'status': 'restarting'}


def connect(address, config, change=None):
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(PinnedKey(config.get('ssh_fingerprint')))
    # Also bound SSH channel setup/exec handshakes, which do not all honor socket timeouts.
    deadline = threading.Timer(45 if change else 20, client.close)
    deadline.daemon = True
    deadline.start()
    try:
        client.connect(address, port=config.get('port') or 22,
            username=config['api_username'], password=config['api_password'],
            allow_agent=False, look_for_keys=False, timeout=4, banner_timeout=4, auth_timeout=4)
        version = execute(client, 'cat /etc/version').decode().strip()
        if not re.match(r'^[A-Z0-9]+\.v[68]\.', version):
            raise ManagementError('This SSH editor supports airOS 6 (M5) and airOS 8 (AC) firmware only.', 422)
        raw = execute(client, 'cat /tmp/system.cfg')
        values, radios = settings(raw)
        if change:
            return change_ssid(client, raw, change)
        data = airos_values(json.loads(execute(client, 'mca-status')), inventory=True)
        return {'vendor': 'Ubiquiti', 'settings': radios, 'restart_on_save': True,
            'wireless': [{'name': r['name'], 'ssid': r['ssid'], 'signal_dbm': data.get('signal_dbm')} for r in radios],
            'ethernet': [{**p, 'status': 'link-ok'} for p in data['ethernet_links']],
            'registrations': data.get('wireless_registrations', []), 'pppoe': [],
            'pppoe_note': 'PPPoE live details are not exposed by this airOS status command.',
            'groups': {'System': [{'Firmware': version, 'Name': values.get('resolv.host.1.name'),
                'Model': data.get('device_model'), 'Uptime (seconds)': data.get('uptime_seconds'),
                'CPU (%)': data.get('cpu_percent'), 'Memory (%)': data.get('memory_percent')}],
                'Network': [{key: value for key, value in values.items() if re.fullmatch(
                    r'(netconf\.[0-9]+\.(devname|ip|netmask|mtu|status)|route\.[0-9]+\.(gateway|ip|netmask)|resolv\.nameserver\.[0-9]+\.ip|bridge\.[0-9]+\.devname)', key)}]},
            'settings_note': 'SSID changes restart the radio. Other settings are available in its web interface.'}
    except TrustRequired as exc:
        if change:
            raise ManagementError('Verify the SSH host key before saving.', 409) from None
        return {'requires_trust': True, 'ssh_fingerprint': exc.fingerprint}
    except paramiko.AuthenticationException:
        raise PermissionError('Device login rejected') from None
    except (paramiko.SSHException, socket.timeout, OSError, EOFError, ValueError):
        raise ManagementError('Ubiquiti SSH is unavailable. Check the login, SSH service and port.', 502) from None
    finally:
        deadline.cancel()
        client.close()
