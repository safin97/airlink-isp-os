"""Destructive settings QA, only inside the disposable AirLink release VM."""
import json
import hashlib
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
sys.path.insert(0, '/opt/airlink/os')
from console import panel_actions as panel


def main():
    assert os.geteuid() == 0
    assert Path('/sys/class/dmi/id/sys_vendor').read_text().strip() == 'AirLinkReleaseQA'
    credentials = json.loads(Path('/var/lib/airlink-release-qa/credentials.json').read_text())
    token = panel.api('POST', '/auth/login', data=credentials)['access_token']
    def api(method, path, data=None): return panel.api(method, path, token, data)
    network = api('GET', '/network')
    interface = next(name for name in network['configurations'])
    assert network['configurations'][interface].get('address')
    original = panel.local_action('settings', {}, token)
    settings = {'confirm': True, 'hostname': 'airlink-panel-qa', 'timezone': 'Europe/Zurich', 'ntp': False, 'manual_time': ''}
    panel.local_action('save_settings', settings, token)
    assert panel.settings_status()['hostname'] == 'airlink-panel-qa'
    assert panel.settings_status()['timezone'] == 'Europe/Zurich'
    # Exercise manual date/time without meaningfully shifting the test machine's clock.
    panel.local_action('save_settings', dict(settings, manual_time=panel.run(['date', '+%Y-%m-%d %H:%M:%S'])), token)
    print('PANEL_QA_HOSTNAME_TIMEZONE_MANUAL_CLOCK_OK', flush=True)
    data = panel.network_payload(interface, 'static', '10.0.2.15', '255.255.255.0', '10.0.2.2', '10.0.2.3', 'airlink-panel-qa')
    pending = api('POST', '/network/apply', data)
    time.sleep(4)
    state = api('GET', '/network')
    assert state['configurations'][interface]['method'] == 'static'
    assert state['configurations'][interface]['gateway'] == '10.0.2.2'
    assert '10.0.2.3' in state['configurations'][interface]['dns']
    api('POST', '/network/confirm', {'checkpoint': pending['checkpoint']})
    assert not api('GET', '/network')['pending']
    print('PANEL_QA_STATIC_IP_MASK_GATEWAY_DNS_CONFIRM_OK', flush=True)
    pending = api('POST', '/network/apply', dict(data, address='10.0.2.16'))
    time.sleep(4)
    api('POST', '/network/restore', {'checkpoint': pending['checkpoint']})
    time.sleep(4)
    assert api('GET', '/network')['configurations'][interface]['address'] == '10.0.2.15'
    api('POST', '/network/apply', dict(data, address='10.0.2.16'))
    print('PANEL_QA_WAITING_FOR_NETWORKMANAGER_120_SECOND_ROLLBACK', flush=True)
    time.sleep(125)
    assert api('GET', '/network')['configurations'][interface]['address'] == '10.0.2.15'
    print('PANEL_QA_EXPLICIT_AND_TIMEOUT_ROLLBACK_OK', flush=True)
    backup = panel.local_action('backup', {'confirm': True}, token)
    selected = Path(backup).name
    assert selected in panel.local_action('backups', {}, token)
    panel.local_action('restore', {'confirm': True, 'backup': selected}, token)
    token = panel.api('POST', '/auth/login', data=credentials)['access_token']
    broken = panel.BACKUPS / 'qa-invalid-restore'
    broken.mkdir(exist_ok=True)
    shutil.copyfile(panel.BACKUPS / selected / 'configuration.tar.gz', broken / 'configuration.tar.gz')
    (broken / 'database.dump').write_bytes(b'invalid database archive')
    (broken / 'SHA256SUMS').write_text(''.join(hashlib.sha256((broken / name).read_bytes()).hexdigest() + '  ' + name + '\n'
                                             for name in ('database.dump', 'configuration.tar.gz')))
    try:
        panel.local_action('restore', {'confirm': True, 'backup': broken.name}, token)
    except ValueError:
        pass
    else:
        raise AssertionError('Invalid database archive was accepted')
    subprocess.run(['bash', '/opt/airlink/deployment/health.sh'], check=True)
    assert api('GET', '/towers')  # The failed transactional restore preserved records.
    print('PANEL_QA_FAILED_RESTORE_RESTARTS_SERVICES_PRESERVES_DATABASE_OK', flush=True)
    assert panel.local_action('logs', {}, token)
    panel.local_action('restart_services', {'confirm': True}, token)
    subprocess.run(['bash', '/opt/airlink/deployment/health.sh'], check=True)
    assert all(value == 'active' for value in api('GET', '/system')['services'].values())
    for _ in range(30):
        if subprocess.run(['pgrep', '-f', '^/usr/bin/python3 /opt/airlink/os/console/panel.py$'], capture_output=True).returncode == 0:
            break
        time.sleep(1)
    else: raise AssertionError('Graphical panel did not start')
    assert subprocess.check_output(['systemctl', 'is-active', 'airlink-console'], text=True).strip() == 'active'
    print('PANEL_QA_BACKUP_RESTORE_LOGS_SERVICES_DISPLAY_OK', flush=True)
    Path('/var/lib/airlink-release-qa/panel-passed').write_text('All local settings checks passed\n')


if __name__ == '__main__':
    main()
