"""Run under Xvfb/Mesa with Debian Python: exercise real Qt probes and launcher.

Example: xvfb-run -a python3 tests/graphics_session_qa.py
The test host must expose software GL only, not a passed-through physical GPU.
"""
import os
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'os'))
from console import graphics

base = graphics.raster_environment(os.environ)
gl = {**base, 'QT_WIDGETS_RHI': '1', 'QT_WIDGETS_RHI_BACKEND': 'opengl',
      'QT_XCB_GL_INTEGRATION': 'xcb_glx'}
assert graphics.qt_works(gl), 'Qt OpenGL must compose a visible frame'
assert not graphics.qt_works(base), 'A software-painted frame must not pass the OpenGL probe'
assert graphics.renderer(gl) is None, 'This test requires software GL, not physical hardware'
selected = graphics.select_environment(os.environ)
assert selected['QT_WIDGETS_RHI'] == '0'
assert selected['AIRLINK_PANEL_RENDERER'] == 'Standard rendering (CPU)'
process = subprocess.Popen([sys.executable, graphics.__file__], env=base,
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
try:
    process.wait(timeout=4)
    raise AssertionError('Launcher exited before it was stopped')
except subprocess.TimeoutExpired:
    pass
finally:
    process.terminate()
    output, errors = process.communicate(timeout=5)
assert b'AirLink local graphics: Standard rendering (CPU)' in output
assert output.count(b'AirLink local graphics:') == 1, 'Stopping must not trigger a restart'
print('QT_OPENGL_FRAME_RASTER_REJECTION_SOFTWARE_FALLBACK_AND_SESSION_STOP_OK')
