import signal
import subprocess
from console import graphics
import pytest


def test_prefers_working_nvidia_and_leaves_service_environment_unchanged(monkeypatch):
    source = {'DISPLAY': ':0', 'AIRLINK_TEST': 'preserved'}
    monkeypatch.setattr(graphics, 'renderer', lambda env, **kw: 'NVIDIA GeForce RTX 4090')
    monkeypatch.setattr(graphics, 'qt_works', lambda env: True)
    result = graphics.select_environment(source)
    assert result['__NV_PRIME_RENDER_OFFLOAD'] == '1'
    assert result['QT_WIDGETS_RHI'] == '1'
    assert result['QT_WIDGETS_RHI_BACKEND'] == 'opengl'
    assert result['AIRLINK_PANEL_RENDERER'].endswith('NVIDIA GeForce RTX 4090')
    assert source == {'DISPLAY': ':0', 'AIRLINK_TEST': 'preserved'}


def test_broken_nvidia_qt_context_falls_back_to_working_default_gpu(monkeypatch):
    monkeypatch.setattr(graphics, 'renderer', lambda env, **kw:
                        'NVIDIA RTX' if '__NV_PRIME_RENDER_OFFLOAD' in env else 'Mesa Intel UHD')
    monkeypatch.setattr(graphics, 'qt_works', lambda env: '__NV_PRIME_RENDER_OFFLOAD' not in env)
    result = graphics.select_environment({'DISPLAY': ':0'})
    assert '__GLX_VENDOR_LIBRARY_NAME' not in result
    assert result['AIRLINK_PANEL_RENDERER'].endswith('Mesa Intel UHD')
    assert result['QT_WIDGETS_RHI'] == '1'


@pytest.mark.parametrize('environment', [{}, {'DISPLAY': ':0', 'QT_QPA_PLATFORM': 'offscreen'}])
def test_headless_does_not_probe(monkeypatch, environment):
    monkeypatch.setattr(graphics, 'renderer', lambda env, **kw: pytest.fail('unexpected probe'))
    assert graphics.select_environment(environment)['QT_WIDGETS_RHI'] == '0'


def test_both_probes_fail_raster_clears_all_nvidia_overrides(monkeypatch):
    monkeypatch.setattr(graphics, 'renderer', lambda env, **kw: None)
    source = {key: 'unwanted' for key in graphics.GRAPHICS_KEYS}
    source['DISPLAY'] = ':0'
    result = graphics.select_environment(source)
    assert '__NV_PRIME_RENDER_OFFLOAD' not in result
    assert '__NV_PRIME_RENDER_OFFLOAD_PROVIDER' not in result
    assert 'QT_WIDGETS_RHI_BACKEND' not in result
    assert result['QT_WIDGETS_RHI'] == '0'


@pytest.mark.parametrize('output,expected', [
    ('direct rendering: Yes\nOpenGL renderer string: NVIDIA GeForce RTX 4090/PCIe/SSE2', 'NVIDIA GeForce RTX 4090/PCIe/SSE2'),
    ('direct rendering: Yes\nOpenGL renderer string: Mesa Intel UHD\n    Accelerated: yes', 'Mesa Intel UHD'),
    ('direct rendering: No\nOpenGL renderer string: NVIDIA RTX', None),
    ('direct rendering: Yes\nOpenGL renderer string: llvmpipe (LLVM 19)', None),
    ('direct rendering: Yes\nOpenGL renderer string: softpipe', None),
    ('direct rendering: Yes\nOpenGL renderer string: Mesa\n    Accelerated: no', None),
    ('', None),
])
def test_gl_probe_reports_only_hardware(monkeypatch, output, expected):
    monkeypatch.setattr(graphics.subprocess, 'run', lambda *a, **kw:
                        subprocess.CompletedProcess(a, 0, output, ''))
    assert graphics.renderer({}) == expected


@pytest.mark.parametrize('vendor,expected', [('NVIDIA Corporation', 'Quadro RTX 4000/PCIe/SSE2'),
                                          ('Mesa', None)])
def test_nvidia_selection_uses_vendor_not_product_name(monkeypatch, vendor, expected):
    output = f'direct rendering: Yes\nOpenGL vendor string: {vendor}\nOpenGL renderer string: Quadro RTX 4000/PCIe/SSE2'
    monkeypatch.setattr(graphics.subprocess, 'run', lambda *a, **kw:
                        subprocess.CompletedProcess(a, 0, output, ''))
    assert graphics.renderer({}, require_nvidia=True) == expected


@pytest.mark.parametrize('error', [FileNotFoundError(), subprocess.TimeoutExpired('probe', 5)])
def test_missing_and_hung_probes_fail_safely(monkeypatch, error):
    def fail(*a, **kw):
        raise error
    monkeypatch.setattr(graphics.subprocess, 'run', fail)
    assert graphics.renderer({}) is None
    assert not graphics.qt_works({})


@pytest.mark.parametrize('code,output,expected', [(0, b'AIRLINK_GL_FRAME_OK', True),
    (-11, b'AIRLINK_GL_FRAME_OK', False), (0, b'', False), (1, b'', False)])
def test_qt_probe_requires_successful_frame(monkeypatch, code, output, expected):
    monkeypatch.setattr(graphics.subprocess, 'run', lambda *a, **kw:
                        subprocess.CompletedProcess(a, code, output, b''))
    assert graphics.qt_works({}) is expected


def test_accelerated_crash_restarts_once_in_raster(monkeypatch):
    launched = []
    monkeypatch.setattr(graphics, 'select_environment', lambda env:
                        {**env, 'QT_WIDGETS_RHI': '1', 'AIRLINK_PANEL_RENDERER': 'NVIDIA'})
    class Child:
        def __init__(self, args, env):
            launched.append(env)
        def wait(self):
            return -11 if len(launched) == 1 else 0
    monkeypatch.setattr(graphics.subprocess, 'Popen', Child)
    assert graphics.run_panel({'DISPLAY': ':0'}) == 0
    assert [env['QT_WIDGETS_RHI'] for env in launched] == ['1', '0']


def test_service_stop_does_not_restart_panel(monkeypatch):
    launched, forwarded = [], []
    monkeypatch.setattr(graphics, 'select_environment', lambda env:
                        {**env, 'QT_WIDGETS_RHI': '1', 'AIRLINK_PANEL_RENDERER': 'NVIDIA'})
    class Child:
        def __init__(self, args, env):
            launched.append(env)
        def wait(self):
            signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)
            return -15
        def poll(self):
            return None
        def send_signal(self, sig):
            forwarded.append(sig)
    monkeypatch.setattr(graphics.subprocess, 'Popen', Child)
    previous = signal.getsignal(signal.SIGTERM)
    assert graphics.run_panel({}) == -15
    assert len(launched) == 1 and forwarded == [signal.SIGTERM]
    assert signal.getsignal(signal.SIGTERM) == previous
