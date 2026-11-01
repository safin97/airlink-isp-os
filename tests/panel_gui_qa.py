"""Run with Debian's Python/PyQt6 and QT_QPA_PLATFORM=offscreen; no real mutations."""
import sys
import time
import subprocess
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'os'))
from PyQt6.QtWidgets import QApplication, QMessageBox
from console import panel

app = QApplication([])
app.setStyleSheet(panel.STYLE)
window = panel.Panel(start=False)
window.resize(1024, 768)
window.show()
calls = []
network = {'hostname': 'airlink-qa', 'interfaces': 'enp0s1:ethernet:connected:DHCP', 'addresses': [],
    'configurations': {'enp0s1': {'method': 'dhcp', 'address': '10.0.2.15', 'prefix': 24, 'gateway': '10.0.2.2', 'dns': ['10.0.2.3']}}, 'pending': None}
settings = {'hostname': 'airlink-qa', 'timezone': 'Europe/Zurich', 'timezones': ['UTC', 'Europe/Zurich'],
    'ntp': False, 'can_ntp': False, 'synchronized': False, 'local_time': '2026-11-01T12:00:00+01:00'}
initialized = False

def api(method, path, token='', data=None):
    global initialized
    calls.append((method, path, data))
    if path == '/setup/status': return {'initialized': initialized}
    if path == '/setup': initialized = True; return {}
    if path == '/auth/login': return {'user': {'role': 'owner'}, 'access_token': 'test-token'}
    if path == '/auth/logout': return {}
    if path == '/system': return {'hostname': 'airlink-qa', 'cpu_percent': 2, 'memory_percent': 12,
        'storage_percent': 8, 'addresses': [], 'services': {'airlink-api': 'active'}}
    if path == '/network': return network
    if path == '/network/apply': return {'checkpoint': '/checkpoints/1', 'rollback_seconds': 120}
    if path == '/network/confirm': return {'confirmed': True}
    if path == '/updates': return {'current_version': '0.1.4-dev', 'state': {'state': {'status': 'installed'}, 'available': None}}
    raise AssertionError(path)

def local(name, data, token):
    assert token == 'test-token'
    calls.append(('local', name, data))
    if name == 'settings': return settings
    if name == 'backups': return ['20261101T110000Z-abcdef']
    if name == 'logs': return 'AirLink API started\nNetworkManager connection active'
    if name == 'save_settings': return 'Settings saved'
    raise AssertionError(name)

panel.actions.api = api
panel.actions.local_action = local
panel.os.environ['AIRLINK_BOOTSTRAP_TOKEN'] = 'test-bootstrap'
window.confirm = lambda *args: True

def settle():
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        app.processEvents()
        if not window.busy:
            app.processEvents()
            if not window.busy: return
        time.sleep(.01)
    raise AssertionError('Worker failed to settle')

out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
window.setup_status(); settle()
assert window.confirm_password.isVisible()
window.grab().save(str(out/'first-owner.png'))
window.username.setText('owner'); window.password.setText('test-password-very-long'); window.confirm_password.setText('test-password-very-long')
window.login(); settle()
assert window.token == 'test-token' and window.password.text() == ''
window.tabs.setCurrentIndex(1); settle()
assert window.interface.currentText() == 'enp0s1' and window.address.text() == '10.0.2.15'
window.method.setCurrentIndex(1)
window.address.setText('192.0.2.10'); window.subnet.setText('255.255.255.0'); window.gateway.setText('192.0.2.1'); window.dns.setText('1.1.1.1,8.8.8.8')
window.apply_network(); settle()
assert window.pending and window.keep.isEnabled() and not window.apply_network_button.isEnabled()
assert next(c[2] for c in calls if c[1] == '/network/apply')['prefix'] == 24
window.grab().save(str(out/'network.png'))
window.finish_network('confirm'); settle()
assert any(c[1] == '/network/confirm' for c in calls)
window.tabs.setCurrentIndex(2); settle()
assert window.hostname.text() == 'airlink-qa' and window.timezone.currentText() == 'Europe/Zurich'
assert not window.ntp.isEnabled() and window.manual_time.isEnabled()
window.grab().save(str(out/'hostname-time.png'))
window.save_settings(); settle()
for index in (3, 4, 5, 6):
    window.tabs.setCurrentIndex(index); settle(); window.grab().save(str(out/f'tab-{index}.png'))
window.last_activity = time.monotonic() - 301
# Finishing a background operation must not reset the inactivity deadline.
window.perform(lambda: 'finished'); settle(); window.tick(); settle()
assert window.token == '' and window.pages.currentIndex() == 0
print('PANEL_GUI_FIRST_SETUP_AUTH_NETWORK_CONFIRM_TIME_SETTINGS_TABS_AUTOLOCK_OK')

# The systemd service executes the script directly; importing it alone misses
# namespace collisions with the legacy console.py in the same directory.
process = subprocess.Popen([sys.executable, str(Path(panel.__file__))], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
try:
    process.wait(timeout=3)
    raise AssertionError('Panel entrypoint exited: ' + process.stderr.read().decode())
except subprocess.TimeoutExpired:
    print('PANEL_DIRECT_ENTRYPOINT_STAYS_RUNNING_OK')
finally:
    process.terminate()
    process.communicate(timeout=5)
