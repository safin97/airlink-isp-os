"""Local-only Qt installer. It is never served over HTTP."""
import os
import sys
import subprocess
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PyQt6.QtCore import QThread, pyqtSignal
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QLabel, QPushButton,
                            QComboBox, QCheckBox, QLineEdit, QPlainTextEdit, QProgressBar, QStackedWidget, QMessageBox)
from installer.disks import discover
from installer.install import install

STYLE = """
QWidget { background: #071426; color: #e4efff; font: 16px 'DejaVu Sans'; }
QLabel#title { font-size: 36px; font-weight: bold; }
QPushButton { background: #1976ed; padding: 14px; border-radius: 7px; }
QPushButton:disabled { background: #26354a; color: #8a9ab0; }
QLineEdit,QComboBox,QPlainTextEdit { background: #10233d; padding: 10px; border: 1px solid #324b6b; }
QProgressBar { border: 1px solid #324b6b; text-align: center; }
QProgressBar::chunk { background: #1976ed; }
"""


class Worker(QThread):
    line = pyqtSignal(str)
    done = pyqtSignal(bool, str)

    def __init__(self, disk):
        super().__init__()
        self.disk = disk

    def run(self):
        try:
            with open("/var/log/airlink-installer.log", "a", buffering=1) as log:
                def emit(line):
                    log.write(line + "\n")
                    self.line.emit(line)
                install(self.disk.path, self.disk.identity, "ERASE", True, emit)
            self.done.emit(True, "Installation successful. Verification checks passed.")
        except Exception as exc:
            self.done.emit(False, str(exc))


class Installer(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("AirLink ISP OS — Installation")
        self.resize(1100, 760)
        self.busy = False
        self.pages = QStackedWidget()
        self.setCentralWidget(self.pages)
        welcome = self.page("AirLink ISP OS", "Network Monitoring Operating System")
        welcome.addWidget(QLabel("UEFI x86_64 • 4 GB RAM minimum • 32 GiB disk minimum\nOffline installation • Secure Boot must be disabled for this development image"))
        self.button(welcome, "Install AirLink ISP OS", lambda: self.pages.setCurrentIndex(1))
        self.button(welcome, "Try Live Mode", self.live)
        language = self.page("Language", "Choose the installation language")
        self.language = QComboBox()
        self.language.addItems(["English"])
        language.addWidget(self.language)
        language.addWidget(QLabel("Only reviewed English translations are included in this release."))
        self.button(language, "Continue", self.refresh_disks)
        disks = self.page("Erase Disk and Install AirLink ISP OS", "All data on the selected disk will be permanently destroyed.")
        self.disk_combo = QComboBox()
        self.disk_combo.currentIndexChanged.connect(self.selection)
        disks.addWidget(self.disk_combo)
        self.detail = QLabel()
        self.detail.setWordWrap(True)
        disks.addWidget(self.detail)
        self.button(disks, "Refresh disks", self.refresh_disks)
        self.ack = QCheckBox("I reviewed the exact disk, model and capacity. Destroy its existing data.")
        disks.addWidget(self.ack)
        self.erase = QLineEdit()
        self.erase.setPlaceholderText("Type ERASE")
        disks.addWidget(self.erase)
        self.go = self.button(disks, "Erase selected disk and install", self.start)
        self.ack.toggled.connect(self.enable)
        self.erase.textChanged.connect(self.enable)
        self.go.setEnabled(False)
        progress = self.page("Installing AirLink ISP OS", "Keep power connected. The installation log is saved locally.")
        self.bar = QProgressBar()
        self.bar.setRange(0, 8)
        progress.addWidget(self.bar)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        progress.addWidget(self.log)
        self.result = QLabel()
        self.result.setWordWrap(True)
        progress.addWidget(self.result)
        self.restart = self.button(progress, "Restart Now", lambda: subprocess.run(["systemctl", "reboot"], check=True))
        self.restart.setEnabled(False)
        self.button(progress, "View Installation Log", lambda: self.log.setPlainText(Path("/var/log/airlink-installer.log").read_text() if Path("/var/log/airlink-installer.log").exists() else "No installation started."))

    def page(self, title, subtitle):
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(50, 40, 50, 40)
        label = QLabel(title)
        label.setObjectName("title")
        layout.addWidget(label)
        label = QLabel(subtitle)
        label.setWordWrap(True)
        layout.addWidget(label)
        self.pages.addWidget(w)
        return layout

    def button(self, layout, label, callback):
        b = QPushButton(label)
        b.clicked.connect(callback)
        layout.addWidget(b)
        return b

    def refresh_disks(self):
        self.disks = discover()
        self.disk_combo.clear()
        for d in self.disks:
            self.disk_combo.addItem(f"{d.path} — {d.model} — {d.size / 1024**3:.1f} GiB" + (" [PROTECTED]" if d.blocked else ""))
        self.selection()
        self.pages.setCurrentIndex(2)

    def selection(self):
        self.ack.setChecked(False)
        self.erase.clear()
        i = self.disk_combo.currentIndex()
        if i >= 0:
            d = self.disks[i]
            self.detail.setText(f"{d.path}\nModel: {d.model}\nCapacity: {d.size:,} bytes\nSerial: {d.serial or 'Not reported'}\nType: {d.transport}\nPartitions: {', '.join(d.partitions) or 'None'}\n" + "\n".join(d.blocked))
        else:
            self.detail.setText("No eligible disks detected.")
        self.enable()

    def enable(self):
        i = self.disk_combo.currentIndex()
        self.go.setEnabled(i >= 0 and not self.disks[i].blocked and self.ack.isChecked() and self.erase.text() == "ERASE")

    def start(self):
        if not self.go.isEnabled():
            return
        self.busy = True
        self.pages.setCurrentIndex(3)
        self.worker = Worker(self.disks[self.disk_combo.currentIndex()])
        self.worker.line.connect(self.line)
        self.worker.done.connect(self.finished)
        self.worker.start()

    def line(self, value):
        self.log.appendPlainText(value)
        if value.startswith("[") and "/8]" in value:
            self.bar.setValue(int(value[1]))

    def finished(self, success, detail):
        self.busy = False
        self.result.setText(detail)
        self.restart.setEnabled(success)
        if not success:
            self.result.setStyleSheet("color: #ff6b7a")

    def live(self):
        subprocess.Popen(["x-terminal-emulator", "-e", "/opt/airlink/venv/bin/python", "/opt/airlink/os/console/console.py"])

    def closeEvent(self, event):
        if self.busy:
            event.ignore()
        else:
            event.accept()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyleSheet(STYLE)
    window = Installer()
    window.show()
    sys.exit(app.exec())
