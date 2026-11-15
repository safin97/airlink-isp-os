"""Choose a working local-display renderer before starting the Qt panel.

Only the panel process receives these settings. Monitoring stays on the CPU.
Qt still rasterizes ordinary widgets on the CPU; RHI composites them with GL.
"""
import os
from pathlib import Path
import signal
import subprocess
import sys

HERE = Path(__file__).resolve().parent
GRAPHICS_KEYS = ('__NV_PRIME_RENDER_OFFLOAD', '__GLX_VENDOR_LIBRARY_NAME',
                 '__NV_PRIME_RENDER_OFFLOAD_PROVIDER', 'QT_WIDGETS_RHI',
                 'QT_WIDGETS_RHI_BACKEND', 'QT_WIDGETS_HIGHDPI_DOWNSCALE', 'QT_XCB_GL_INTEGRATION',
                 'AIRLINK_PANEL_RENDERER')


def raster_environment(environment):
    result = dict(environment)
    for key in GRAPHICS_KEYS:
        result.pop(key, None)
    result['QT_WIDGETS_RHI'] = '0'
    result['AIRLINK_PANEL_RENDERER'] = 'Standard rendering (CPU)'
    return result


def renderer(environment, require_nvidia=False):
    """Require a direct hardware GL renderer; never mislabel llvmpipe as GPU."""
    try:
        result = subprocess.run(['/usr/bin/glxinfo', '-B'], env={**environment, 'LC_ALL': 'C'},
                                capture_output=True, text=True, timeout=5, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if result.returncode:
        return None
    values = dict(line.strip().split(': ', 1) for line in result.stdout.splitlines()
                  if ': ' in line)
    name = values.get('OpenGL renderer string', '').strip()
    if require_nvidia and 'nvidia' not in values.get('OpenGL vendor string', '').lower():
        return None
    if (not name or values.get('direct rendering') != 'Yes'
            or values.get('Accelerated', '').lower() == 'no'
            or any(x in name.lower() for x in ('llvmpipe', 'softpipe', 'swrast', 'software'))):
        return None
    return name[:200]


def qt_works(environment):
    """Probe out-of-process so a broken driver cannot crash the panel launcher."""
    try:
        result = subprocess.run([sys.executable, str(HERE / 'graphics_probe.py')],
                                env=environment, capture_output=True, timeout=8, check=False)
        return result.returncode == 0 and b'AIRLINK_GL_FRAME_OK' in result.stdout
    except (OSError, subprocess.TimeoutExpired):
        return False


def select_environment(environment):
    base = raster_environment(environment)
    if not base.get('DISPLAY') or base.get('QT_QPA_PLATFORM', 'xcb') != 'xcb':
        return base
    gl = {**base, 'QT_WIDGETS_RHI': '1', 'QT_WIDGETS_RHI_BACKEND': 'opengl',
          'QT_XCB_GL_INTEGRATION': 'xcb_glx'}
    # NVIDIA-only systems and PRIME hybrid systems both use GLVND selection.
    nvidia = {**gl, '__NV_PRIME_RENDER_OFFLOAD': '1', '__GLX_VENDOR_LIBRARY_NAME': 'nvidia'}
    for candidate, require_nvidia in ((nvidia, True), (gl, False)):
        name = renderer(candidate, require_nvidia=require_nvidia)
        if name and qt_works(candidate):
            candidate['AIRLINK_PANEL_RENDERER'] = f'OpenGL compositing — {name}'
            return candidate
    return base


def run_panel(environment):
    """One raster retry on a graphics crash; intentional service stops stay stopped."""
    selected = select_environment(environment)
    child = None
    stopping = False

    def stop(signum, frame):
        nonlocal stopping
        stopping = True
        if child is not None and child.poll() is None:
            child.send_signal(signum)

    previous = {sig: signal.signal(sig, stop) for sig in (signal.SIGTERM, signal.SIGINT)}
    try:
        for settings in (selected, raster_environment(environment)):
            if stopping:
                return 0
            print('AirLink local graphics: ' + settings['AIRLINK_PANEL_RENDERER'], flush=True)
            child = subprocess.Popen([sys.executable, str(HERE / 'panel.py')], env=settings)
            if stopping:
                child.terminate()
            code = child.wait()
            if stopping or code == 0 or settings['QT_WIDGETS_RHI'] == '0':
                return code
            print('AirLink local graphics: restarting panel with standard rendering.', flush=True)
        return code
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


if __name__ == '__main__':
    sys.exit(run_panel(os.environ))
