"""Owner-authenticated settings panel on the installed appliance's local display."""
import os
import sys
import time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PyQt6.QtCore import QEvent, QThread, QTimer, Qt, pyqtSignal
from PyQt6.QtGui import QIcon, QPixmap
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QFormLayout, QLabel, QPushButton, QLineEdit, QComboBox, QCheckBox, QPlainTextEdit,
    QStackedWidget, QTabWidget, QScrollArea, QMessageBox)
from console import panel_actions as actions

BRANDING = Path(__file__).resolve().parents[1] / 'branding'
STYLE = '''
QWidget { background: #071426; color: #e4efff; font: 15px 'DejaVu Sans'; }
QLabel#title { font-size: 25px; font-weight: bold; }
QLabel#brand { background: white; border-radius: 8px; }
QPushButton { background: #1976ed; padding: 10px 18px; border-radius: 6px; }
QPushButton:disabled { background: #26354a; color: #8a9ab0; }
QLineEdit,QComboBox,QPlainTextEdit { background: #10233d; padding: 8px; border: 1px solid #324b6b; }
QTabBar::tab { background: #10233d; padding: 12px 10px; }
QTabBar::tab:selected { background: #1976ed; }
QCheckBox { padding: 6px; }
QScrollArea { border: none; }
'''


class Worker(QThread):
    result = pyqtSignal(object, object)

    def __init__(self, task):
        super().__init__()
        self.task = task

    def run(self):
        try:
            self.value, self.error = self.task(), None
        except Exception as exc:
            self.value, self.error = None, exc


class Panel(QMainWindow):
    def __init__(self, start=True):
        super().__init__()
        self.setWindowTitle('AirLink ISP OS — Local settings')
        self.setWindowIcon(QIcon(str(BRANDING / 'airlink-stacked.png')))
        self.resize(1100, 760)
        self.token = ''
        self.busy = False
        self.initialized = None
        self.pending = None
        self.network_state = {}
        self.available = None
        self.last_activity = time.monotonic()
        self.last_probe = 0
        self.central = QWidget()
        self.setCentralWidget(self.central)
        layout = QVBoxLayout(self.central)
        layout.setContentsMargins(24, 16, 24, 16)
        heading = QHBoxLayout()
        logo = QLabel()
        logo.setObjectName('brand')
        logo.setFixedSize(180, 74)
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo.setPixmap(QPixmap(str(BRANDING / 'airlink-horizontal.png')).scaled(172, 68, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        heading.addWidget(logo)
        title = QLabel('PC settings')
        title.setObjectName('title')
        heading.addWidget(title)
        heading.addStretch()
        self.lock_button = QPushButton('Lock panel')
        self.lock_button.clicked.connect(self.lock)
        self.lock_button.setVisible(False)
        heading.addWidget(self.lock_button)
        layout.addLayout(heading)
        self.message = QLabel('Connecting to AirLink…')
        self.message.setWordWrap(True)
        layout.addWidget(self.message)
        self.pages = QStackedWidget()
        layout.addWidget(self.pages, 1)
        self.build_login()
        self.tabs = QTabWidget()
        self.pages.addWidget(self.tabs)
        self.build_overview()
        self.build_network()
        self.build_settings()
        self.build_updates()
        self.build_backups()
        self.build_logs()
        self.build_system()
        self.tabs.currentChanged.connect(self.refresh_page)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.tick)
        self.timer.start(1000)
        QApplication.instance().installEventFilter(self)
        if start:
            QTimer.singleShot(0, self.setup_status)

    def eventFilter(self, obj, event):
        if event.type() in (QEvent.Type.MouseButtonPress, QEvent.Type.KeyPress, QEvent.Type.TouchBegin):
            self.last_activity = time.monotonic()
        return super().eventFilter(obj, event)

    def closeEvent(self, event):
        event.ignore()  # This is the appliance console, not a route to a root desktop.

    def button(self, layout, label, callback):
        button = QPushButton(label)
        button.clicked.connect(callback)
        layout.addWidget(button)
        return button

    def tab(self, title):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(20, 18, 20, 18)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(page)
        self.tabs.addTab(scroll, title)
        return layout

    def text(self, layout):
        widget = QPlainTextEdit()
        widget.setReadOnly(True)
        layout.addWidget(widget, 1)
        return widget

    def note(self, layout, text):
        label = QLabel(text)
        label.setWordWrap(True)
        layout.addWidget(label)
        return label

    def perform(self, task, done=None, message='Working…'):
        if self.busy:
            return
        self.busy = True
        self.pages.setEnabled(False)
        self.lock_button.setEnabled(False)
        self.message.setText(message)
        self.worker = Worker(task)
        worker = self.worker
        worker.finished.connect(lambda: self.completed(worker.value, worker.error, done))
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def completed(self, value, error, done):
        self.busy = False
        self.pages.setEnabled(True)
        self.lock_button.setEnabled(True)
        if error:
            if isinstance(error, actions.SessionExpired):
                self.lock()
            self.message.setText(str(error))
        else:
            self.message.setText('Ready')
            if done:
                done(value)

    def confirm(self, title, text):
        return QMessageBox.question(self, title, text, QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                    QMessageBox.StandardButton.No) == QMessageBox.StandardButton.Yes

    def build_login(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.addStretch()
        self.login_heading = self.note(layout, 'Sign in with your AirLink owner account.')
        form = QFormLayout()
        self.username = QLineEdit()
        self.password = QLineEdit()
        self.password.setEchoMode(QLineEdit.EchoMode.Password)
        self.confirm_password = QLineEdit()
        self.confirm_password.setEchoMode(QLineEdit.EchoMode.Password)
        form.addRow('Owner username', self.username)
        form.addRow('Password', self.password)
        self.confirm_label = QLabel('Confirm password')
        form.addRow(self.confirm_label, self.confirm_password)
        layout.addLayout(form)
        self.signin = self.button(layout, 'Sign in', self.login)
        self.password.returnPressed.connect(self.login)
        self.button(layout, 'Retry connection', self.setup_status)
        self.note(layout, 'Network, hostname, date/time and system controls are available after owner sign-in.\nThe panel locks after five minutes without activity. No default password exists.')
        layout.addStretch()
        self.pages.addWidget(page)

    def setup_status(self):
        self.last_probe = time.monotonic()
        def ready(value):
            self.initialized = value['initialized']
            self.confirm_password.setVisible(not self.initialized)
            self.confirm_label.setVisible(not self.initialized)
            self.signin.setText('Sign in' if self.initialized else 'Create owner account')
            self.login_heading.setText('Sign in with your AirLink owner account.' if self.initialized else
                                       'Welcome. Create the first owner account (password: 14–128 characters).')
            self.message.setText('AirLink is ready')
        self.perform(lambda: actions.api('GET', '/setup/status'), ready)

    def login(self):
        if self.initialized is None:
            self.setup_status()
            return
        username, password, confirmation = self.username.text().strip(), self.password.text(), self.confirm_password.text()
        first = not self.initialized
        def task():
            if first:
                bootstrap = os.environ.get('AIRLINK_BOOTSTRAP_TOKEN', '')
                if not bootstrap:
                    raise ValueError('Local setup token unavailable; check the console service configuration')
                actions.api('POST', '/setup', data={'username': username, 'password': password,
                    'confirm_password': confirmation, 'token': bootstrap})
            result = actions.api('POST', '/auth/login', data={'username': username, 'password': password})
            if result['user']['role'] != 'owner':
                actions.api('POST', '/auth/logout', result['access_token'])
                raise ValueError('Only the owner can administer this PC')
            return result
        def ready(result):
            self.initialized = True
            self.token = result['access_token']
            self.password.clear()
            self.confirm_password.clear()
            self.pages.setCurrentIndex(1)
            self.lock_button.setVisible(True)
            self.tabs.setCurrentIndex(0)
            self.refresh_page()
        self.perform(task, ready, 'Signing in…')

    def lock(self):
        if self.busy:
            return
        old_token = self.token
        self.token = ''
        self.password.clear()
        self.confirm_password.clear()
        self.logs.clear()
        self.pages.setCurrentIndex(0)
        self.lock_button.setVisible(False)
        if old_token:
            self.perform(lambda: actions.api('POST', '/auth/logout', old_token), lambda _: self.message.setText('Panel locked'))

    def build_overview(self):
        layout = self.tab('Overview')
        self.note(layout, 'Use the tabs to configure this PC. Open the HTTPS address below from another computer to manage towers, devices and users.')
        self.overview = self.text(layout)
        self.button(layout, 'Refresh status', self.refresh_page)

    def show_overview(self, data):
        lines = ['Hostname: ' + data['hostname'],
                 f"CPU: {data['cpu_percent']}%    Memory: {data['memory_percent']}%    Disk used: {data['storage_percent']}%", '', 'Dashboard addresses:']
        for interface in data['addresses']:
            for address in interface.get('addr_info', []):
                if address.get('scope') == 'global':
                    ip = address['local']
                    lines.append(f"  {interface['ifname']} — https://{'[' + ip + ']' if ':' in ip else ip}")
        lines += ['', 'Services:'] + [name + ': ' + value for name, value in data['services'].items()]
        self.overview.setPlainText('\n'.join(lines))

    def build_network(self):
        layout = self.tab('Network')
        self.note(layout, 'Set the management Ethernet connection. Changes revert after 120 seconds unless you choose Keep settings.')
        form = QFormLayout()
        self.interface = QComboBox()
        self.interface.currentTextChanged.connect(self.fill_network)
        self.method = QComboBox()
        self.method.addItems(['Automatic (DHCP)', 'Static IPv4'])
        self.method.currentIndexChanged.connect(self.network_enabled)
        self.address, self.subnet, self.gateway, self.dns = (QLineEdit() for _ in range(4))
        self.subnet.setPlaceholderText('24 or 255.255.255.0')
        self.dns.setPlaceholderText('1.1.1.1, 8.8.8.8')
        for label, field in [('Interface', self.interface), ('Address mode', self.method), ('IP address', self.address),
                             ('Subnet / mask', self.subnet), ('Gateway', self.gateway), ('DNS servers', self.dns)]:
            form.addRow(label, field)
        layout.addLayout(form)
        self.network_detail = self.note(layout, '')
        row = QHBoxLayout()
        self.apply_network_button = self.button(row, 'Apply network settings', self.apply_network)
        self.button(row, 'Reload current settings', self.load_network)
        layout.addLayout(row)
        self.pending_label = self.note(layout, '')
        row = QHBoxLayout()
        self.keep = self.button(row, 'Keep settings', lambda: self.finish_network('confirm'))
        self.revert = self.button(row, 'Revert settings', lambda: self.finish_network('restore'))
        layout.addLayout(row)
        self.keep.setEnabled(False)
        self.revert.setEnabled(False)
        layout.addStretch()
        self.network_enabled()

    def network_enabled(self):
        for field in (self.address, self.subnet, self.gateway, self.dns):
            field.setEnabled(self.method.currentIndex() == 1)

    def load_network(self):
        self.perform(lambda: actions.api('GET', '/network', self.token), self.show_network)

    def show_network(self, data):
        self.network_state = data
        self.pending = data.get('pending')
        selected = self.interface.currentText()
        names = [line.split(':')[0] for line in data['interfaces'].splitlines() if ':ethernet:' in line]
        self.interface.blockSignals(True)
        self.interface.clear()
        self.interface.addItems(names)
        if selected in names:
            self.interface.setCurrentText(selected)
        self.interface.blockSignals(False)
        self.fill_network()
        self.tick()

    def fill_network(self):
        data = self.network_state
        name = self.interface.currentText()
        active = data.get('configurations', {}).get(name, {})
        self.network_hostname = data.get('hostname', 'airlink')
        self.method.setCurrentIndex(1 if active.get('method') == 'static' else 0)
        self.address.setText(active.get('address', ''))
        self.subnet.setText(str(active.get('prefix', 24)))
        self.gateway.setText(active.get('gateway', ''))
        self.dns.setText(', '.join(active.get('dns', [])))
        self.network_detail.setText('Active address: ' + (active.get('address') or 'No IPv4 address') +
                                    '\nHostname: ' + self.network_hostname)

    def apply_network(self):
        try:
            payload = actions.network_payload(self.interface.currentText(), 'static' if self.method.currentIndex() else 'dhcp',
                self.address.text(), self.subnet.text(), self.gateway.text(), self.dns.text(), self.network_hostname)
        except ValueError as exc:
            self.message.setText(str(exc))
            return
        if not self.confirm('Apply network settings?', 'This changes the management network connection. Check connectivity, then keep the settings within two minutes.'):
            return
        def done(value):
            self.pending = {'checkpoint': value['checkpoint'], 'deadline': time.time() + value['rollback_seconds']}
            self.message.setText('Network change applied temporarily. Verify connectivity, then choose Keep settings.')
            self.tick()
        self.perform(lambda: actions.api('POST', '/network/apply', self.token, payload), done)

    def finish_network(self, operation):
        if not self.pending:
            return
        payload = {'checkpoint': self.pending['checkpoint']}
        self.perform(lambda: actions.api('POST', '/network/' + operation, self.token, payload), lambda _: self.load_network())

    def build_settings(self):
        layout = self.tab('Hostname && time')
        self.note(layout, 'Set this PC’s hostname and local timezone. Leave manual date/time empty to keep the current clock. Clock changes may end your login session.')
        form = QFormLayout()
        self.hostname = QLineEdit()
        self.timezone = QComboBox()
        self.timezone.setEditable(True)
        self.ntp = QCheckBox('Automatic time synchronization')
        self.manual_time = QLineEdit()
        self.manual_time.setPlaceholderText('YYYY-MM-DD HH:MM:SS (in the selected timezone)')
        self.ntp.toggled.connect(lambda value: self.manual_time.setEnabled(not value))
        for label, field in [('Hostname', self.hostname), ('Timezone', self.timezone), ('Time source', self.ntp), ('Manual date/time', self.manual_time)]:
            form.addRow(label, field)
        layout.addLayout(form)
        self.clock_info = self.note(layout, '')
        self.button(layout, 'Save hostname and time settings', self.save_settings)
        self.button(layout, 'Reload current settings', self.load_settings)
        layout.addStretch()

    def load_settings(self):
        self.perform(lambda: actions.local_action('settings', {}, self.token), self.show_settings)

    def show_settings(self, data):
        self.hostname.setText(data['hostname'])
        self.timezone.clear()
        self.timezone.addItems(data['timezones'])
        self.timezone.setCurrentText(data['timezone'])
        self.ntp.setEnabled(data['can_ntp'])
        self.ntp.setChecked(data['ntp'])
        self.manual_time.clear()
        self.manual_time.setEnabled(not data['ntp'])
        self.clock_info.setText('Current local time: ' + data['local_time'] + '\n' +
            ('Time synchronized: ' + ('Yes' if data['synchronized'] else 'No') if data['can_ntp'] else
             'Automatic time is unavailable: no NTP service is installed. Manual date/time and timezone are available.'))

    def save_settings(self):
        data = {'hostname': self.hostname.text().strip(), 'timezone': self.timezone.currentText(),
                'ntp': self.ntp.isChecked(), 'manual_time': self.manual_time.text().strip(), 'confirm': True}
        if self.confirm('Save system settings?', 'Apply hostname and date/time settings? A manual clock change can end your session and affect scheduled updates.'):
            self.perform(lambda: actions.local_action('save_settings', data, self.token), lambda value: self.message.setText(value))

    def build_updates(self):
        layout = self.tab('Updates')
        self.note(layout, 'Get signed AirLink application releases from GitHub without opening a browser.')
        self.update_text = self.text(layout)
        row = QHBoxLayout()
        for label, action in [('Check for updates', 'check'), ('Download & verify', 'download'), ('Install update', 'install')]:
            self.button(row, label, lambda _, name=action: self.update_action(name))
        layout.addLayout(row)
        self.schedule = QLineEdit()
        self.schedule.setPlaceholderText('Schedule: YYYY-MM-DDTHH:MM:SS+02:00 (include UTC offset)')
        layout.addWidget(self.schedule)
        row = QHBoxLayout()
        self.button(row, 'Schedule update', lambda: self.update_action('schedule'))
        self.button(row, 'Restart system', self.restart)
        self.button(row, 'Refresh status', self.load_updates)
        layout.addLayout(row)

    def load_updates(self):
        self.perform(lambda: actions.api('GET', '/updates', self.token), self.show_updates)

    def show_updates(self, data):
        state = data['state']
        self.available = state.get('available')
        operation = state.get('state', {})
        transfer = state.get('transfer', {})
        lines = ['Installed version: ' + data['current_version'],
                 'Available version: ' + (self.available or {}).get('version', 'None — check for updates'),
                 'Installation: ' + operation.get('status', 'idle')]
        if operation.get('error'):
            lines.append('Error: ' + operation['error'])
        if transfer:
            lines.append('Download: ' + transfer.get('status', '') + f"  {transfer.get('received', 0)} / {transfer.get('total', 0)} bytes")
        check = state.get('last_check') or {}
        if check.get('up_to_date'):
            lines.append('You are up to date.')
        if check.get('error'):
            lines.append('Last check: ' + check['error'])
        self.update_text.setPlainText('\n'.join(lines))

    def update_action(self, name):
        data = {key: self.available[key] for key in ('version', 'sequence')} if self.available else {}
        if name in ('install', 'schedule'):
            if not self.confirm('Install software update?', 'The update must be downloaded and verified first. AirLink services and this panel may restart during installation.'):
                return
        if name == 'schedule':
            data['at'] = self.schedule.text().strip()
        self.perform(lambda: actions.api('POST', '/updates/' + name, self.token, data), lambda _: self.load_updates(), 'Update operation in progress…')

    def build_backups(self):
        layout = self.tab('Backups')
        self.note(layout, 'Local backups include the database and configuration archives. Database restore replaces current records and creates a safety backup first. Configuration files require manual recovery review.')
        self.backups = QComboBox()
        layout.addWidget(self.backups)
        self.button(layout, 'Refresh backup list', self.load_backups)
        self.button(layout, 'Create backup', lambda: self.maintenance('backup', 'Create a local database and configuration backup?'))
        self.button(layout, 'Restore selected database', self.restore)
        layout.addStretch()

    def load_backups(self):
        def done(items):
            self.backups.clear()
            self.backups.addItems(list(reversed(items)))
        self.perform(lambda: actions.local_action('backups', {}, self.token), done)

    def restore(self):
        if not self.backups.currentText():
            self.message.setText('Select a backup first')
            return
        self.maintenance('restore', 'Replace the current database with ' + self.backups.currentText() + '? You will need to sign in again.',
                         {'backup': self.backups.currentText()})

    def build_logs(self):
        layout = self.tab('Logs')
        self.logs = self.text(layout)
        self.button(layout, 'Refresh recent system logs', self.load_logs)

    def load_logs(self):
        self.perform(lambda: actions.local_action('logs', {}, self.token), self.logs.setPlainText)

    def build_system(self):
        layout = self.tab('System')
        self.note(layout, 'Restart services or safely restart/shut down this PC. Power actions are blocked during an update or when a failed installation needs review.')
        self.button(layout, 'Restart AirLink services', lambda: self.maintenance('restart_services', 'Briefly interrupt monitoring and dashboard access to restart AirLink services?'))
        self.button(layout, 'Restart system', self.restart)
        self.button(layout, 'Shut down system', lambda: self.maintenance('shutdown', 'Shut down this PC? Monitoring will stop until it is powered on again.'))
        self.note(layout, 'For recovery, use the AirLink recovery option on the installer media. Keep backups on another device as well as on this PC.')
        layout.addStretch()

    def maintenance(self, name, question, data=None):
        if not self.confirm('Confirm operation', question):
            return
        payload = dict(data or {}, confirm=True)
        def done(value):
            if name == 'restore':
                self.lock()
            self.message.setText(str(value) if name != 'shutdown' else 'Shutdown requested. This PC will turn off shortly.')
        self.perform(lambda: actions.local_action(name, payload, self.token), done, 'System operation in progress…')

    def restart(self):
        if self.confirm('Restart system?', 'Restart this PC now? Monitoring and dashboard access will be interrupted briefly.'):
            self.perform(lambda: actions.api('POST', '/system/restart', self.token, {'confirm': True}),
                         lambda _: self.message.setText('Restart requested. The panel will return after the PC restarts.'))

    def refresh_page(self, *_):
        if not self.token or self.busy:
            return
        index = self.tabs.currentIndex()
        if index == 0:
            self.perform(lambda: actions.api('GET', '/system', self.token), self.show_overview)
        elif index == 1:
            self.load_network()
        elif index == 2:
            self.load_settings()
        elif index == 3:
            self.load_updates()
        elif index == 4:
            self.load_backups()
        elif index == 5:
            self.load_logs()

    def tick(self):
        if self.initialized is None and not self.busy and time.monotonic() - self.last_probe >= 5:
            self.setup_status()
        if self.token and not self.busy and time.monotonic() - self.last_activity >= 300:
            self.lock()
        remaining = int(self.pending['deadline'] - time.time()) if self.pending else 0
        active = remaining > 0
        self.keep.setEnabled(active)
        self.revert.setEnabled(active)
        self.apply_network_button.setEnabled(not active)
        self.pending_label.setText(f'Keep or revert the temporary settings: {remaining}s remaining.' if active else
                                  ('Confirmation expired. NetworkManager restores the previous connection.' if self.pending else ''))


if __name__ == '__main__':
    app = QApplication(sys.argv)
    app.setStyleSheet(STYLE)
    panel = Panel()
    # xinit intentionally runs without a desktop/window manager. Explicitly
    # size the window too, since an EWMH fullscreen request may be ignored.
    panel.setGeometry(app.primaryScreen().geometry())
    panel.showFullScreen()
    sys.exit(app.exec())
