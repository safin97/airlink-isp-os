"""Headless Qt check; no screenshots and no system changes."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'os'))
from PyQt6.QtWidgets import QApplication
from console.panel import Panel

app = QApplication([])
panel = Panel(start=False)
base = {'hostname': 'gpu-test', 'cpu_percent': 0, 'memory_percent': 5,
        'storage_percent': 8, 'addresses': [], 'services': {'airlink-api': 'active'}}
panel.show_overview(base)
assert 'No PCI graphics processor detected.' in panel.overview.toPlainText()
panel.show_overview({**base, 'gpus': [{'name': 'NVIDIA GeForce RTX 4090',
    'driver': 'nvidia', 'status': 'ready', 'driver_version': '610.57.04',
    'memory_total_mib': 24564, 'memory_used_mib': 10, 'utilization_percent': 0,
    'temperature_c': 32}]})
text = panel.overview.toPlainText()
assert 'NVIDIA GeForce RTX 4090' in text and 'NVIDIA driver ready' in text
assert 'GPU: 0%' in text and 'VRAM total: 24564 MiB' in text and 'Temperature: 32 °C' in text
panel.show_overview({**base, 'gpus': [{'name': 'NVIDIA 0x2484', 'driver': None, 'status': 'not_loaded'}]})
assert 'Driver not loaded' in panel.overview.toPlainText()
panel.close()
print('GPU_PANEL_DETECTION_STATUS_AND_TELEMETRY_OK')
