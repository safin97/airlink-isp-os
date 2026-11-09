import os
from pathlib import Path
import subprocess
import sys

import pytest

from updates import update


@pytest.fixture
def health_commands(tmp_path):
    """Run the real shell check with controlled service startup timings."""
    commands = tmp_path / 'bin'
    commands.mkdir()
    stub = commands / 'command'
    stub.write_text(f'#!{Path(sys.executable).resolve()}\n' + '''
import os
from pathlib import Path
import sys

counter = Path(os.environ['HEALTH_TEST_COUNTER'])
attempt = int(counter.read_text()) if counter.exists() else 0
command = Path(sys.argv[0]).name
scenario = os.environ['HEALTH_TEST_SCENARIO']
if command == 'sleep':
    counter.write_text(str(attempt + 1))
elif command == 'curl':
    sys.exit(22 if scenario == 'api_down' else 0)
elif command == 'systemctl':
    if sys.argv[-1] == 'airlink-monitor':
        sys.exit(3 if scenario == 'service_down' or
                 (scenario == 'slow_start' and attempt < 2) else 0)
elif command == 'redis-cli':
    if scenario == 'redis_down':
        sys.exit(1)
    ready = not (scenario == 'missing_heartbeat' or
                 (scenario == 'slow_start' and attempt < 3))
    print(1 if ready else 0)
''')
    stub.chmod(0o755)
    for name in ('curl', 'systemctl', 'redis-cli', 'sleep'):
        (commands / name).symlink_to(stub)

    def run(scenario):
        result = subprocess.run(
            ['/bin/bash', str(Path(__file__).resolve().parents[1] / 'deployment/health.sh')],
            env={**os.environ, 'PATH': str(commands) + os.pathsep + os.environ['PATH'],
                 'HEALTH_TEST_COUNTER': str(tmp_path / 'attempt'),
                 'HEALTH_TEST_SCENARIO': scenario},
            capture_output=True, text=True, timeout=30,
        )
        attempts = tmp_path / 'attempt'
        return result, int(attempts.read_text()) if attempts.exists() else 0
    return run


def test_health_waits_for_workers_after_api_is_ready(health_commands):
    result, waits = health_commands('slow_start')
    assert result.returncode == 0, result.stderr
    assert waits == 3
    assert 'health check passed' in result.stdout


def test_health_ready_needs_no_wait(health_commands):
    result, waits = health_commands('ready')
    assert result.returncode == 0
    assert waits == 0


@pytest.mark.parametrize('scenario, detail', [
    ('api_down', 'API/database/Redis endpoint unavailable'),
    ('service_down', 'airlink-monitor service is not active'),
    ('missing_heartbeat', 'monitor worker heartbeat unavailable'),
    ('redis_down', 'alerts worker heartbeat unavailable'),
])
def test_health_failure_names_component_and_remains_failure(health_commands, scenario, detail):
    result, waits = health_commands(scenario)
    assert result.returncode == 1
    assert waits == 29
    assert f'AirLink health check failed: {detail}' in result.stderr


def test_update_health_error_keeps_component_details_only(monkeypatch):
    diagnostic = 'AirLink health check failed: alerts worker heartbeat unavailable'
    monkeypatch.setattr(update.subprocess, 'run', lambda *args, **kwargs:
                        subprocess.CompletedProcess(args[0], 1, '', 'unrelated output\n' + diagnostic + '\n'))
    with pytest.raises(RuntimeError) as exc:
        update.health_check()
    assert str(exc.value) == diagnostic


def test_update_old_health_script_has_fallback_error(monkeypatch):
    monkeypatch.setattr(update.subprocess, 'run', lambda *args, **kwargs:
                        subprocess.CompletedProcess(args[0], 1, '', ''))
    with pytest.raises(RuntimeError, match='review the update journal'):
        update.health_check()
