import json
import pytest
from airlink import airos_management as air
from airlink.device_management import ManagementError

RAW = b'wireless.1.devname=ath0\nwireless.1.ssid=Before\nusers.1.password=SECRET\nnetconf.1.ip=10.2.3.4\n'
CHANGE = {'menu': 'wireless', 'radio_id': '*1', 'previous_ssid': 'Before', 'ssid': 'After'}


def test_ssid_save_preserves_other_configuration_and_never_interpolates_user_input(monkeypatch):
    calls = []
    def execute(client, command, content=None):
        calls.append((command, content))
        return RAW if command == 'cat /tmp/system.cfg' else b''
    monkeypatch.setattr(air, 'execute', execute)
    result = air.change_ssid(None, RAW, {**CHANGE, 'ssid': 'Name $(touch /bad);test'})
    assert result['status'] == 'restarting'
    upload = next(content for _, content in calls if content is not None)
    assert upload == RAW.replace(b'ssid=Before', b'ssid=Name $(touch /bad);test')
    assert all('touch' not in command and 'SECRET' not in command for command, _ in calls)
    assert len([c for c, _ in calls if c.startswith('cfgmtd')]) == 1
    assert 'reboot' in calls[-1][0]


@pytest.mark.parametrize('scenario', ['stale_ssid', 'stale_config', 'duplicate', 'bad_format', 'unknown_write'])
def test_rejects_stale_or_ambiguous_config_and_does_not_retry_unknown_write(monkeypatch, scenario):
    writes = []
    def execute(client, command, content=None):
        if command == 'cat /tmp/system.cfg':
            return RAW + b'new.setting=yes\n' if scenario == 'stale_config' else RAW
        writes.append(command)
        if command.startswith('cfgmtd'):
            raise OSError('Private error must not leak')
        return b''
    monkeypatch.setattr(air, 'execute', execute)
    raw = RAW + b'wireless.1.ssid=Duplicate\n' if scenario == 'duplicate' else RAW
    change = {**CHANGE, **({'previous_ssid': 'Wrong'} if scenario == 'stale_ssid' else {}),
              **({'ssid': 'a\\b'} if scenario == 'bad_format' else {})}
    with pytest.raises(ManagementError) as exc:
        air.change_ssid(None, raw, change)
    assert 'Private' not in str(exc.value)
    assert len([c for c in writes if c.startswith('cfgmtd')]) == (1 if scenario == 'unknown_write' else 0)
    assert not any('reboot' in c for c in writes)


def test_host_key_is_verified_before_authentication():
    class Key:
        def asbytes(self): return b'public-host-key'
    with pytest.raises(air.TrustRequired) as challenge:
        air.PinnedKey(None).missing_host_key(None, '10.2.3.4', Key())
    fingerprint = challenge.value.fingerprint
    assert fingerprint.startswith('SHA256:')
    air.PinnedKey(fingerprint).missing_host_key(None, '10.2.3.4', Key())
    with pytest.raises(ManagementError):
        air.PinnedKey('wrong').missing_host_key(None, '10.2.3.4', Key())


@pytest.mark.parametrize('version', ['XM.v6.3.11', 'WA.v8.7.12'])
def test_m5_and_ac_reads_never_expose_config_passwords(monkeypatch, version):
    class Client:
        def set_missing_host_key_policy(self, policy): pass
        def connect(self, *a, **kw):
            assert kw['look_for_keys'] is False and kw['allow_agent'] is False
        def close(self): pass
    monkeypatch.setattr(air.paramiko, 'SSHClient', Client)
    def execute(client, command):
        if command == 'cat /etc/version': return version.encode()
        if command == 'cat /tmp/system.cfg': return RAW
        if command == 'mca-status': return json.dumps({'wireless': {'mode': 'sta', 'signal': -61, 'essid': 'Before'},
            'interfaces': [{'ifname': 'eth0', 'status': {'plugged': 1, 'speed': 1000}}]}).encode()
        pytest.fail('Unexpected command')
    monkeypatch.setattr(air, 'execute', execute)
    result = air.connect('10.2.3.4', {'api_username': 'user', 'api_password': 'password'})
    assert result['settings'][0]['ssid'] == 'Before'
    assert result['ethernet'][0]['speed_mbps'] == 1000
    assert result['wireless'][0]['signal_dbm'] == -61
    assert 'SECRET' not in json.dumps(result) and 'password' not in json.dumps(result)
