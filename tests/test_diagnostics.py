from types import SimpleNamespace

from airlink import api
from console import broker


def test_diagnostics_endpoint_is_settings_protected(client, owner, monkeypatch):
    payload = {
        'status': 'problems',
        'checked_at': 1,
        'problems': [{'severity': 'critical', 'source': 'update', 'title': 'Update failed', 'detail': 'migration failed'}],
        'services': {'airlink-api': 'active'},
        'resources': {'cpu_percent': 2, 'memory_percent': 20, 'storage_percent': 30},
        'update': {'status': 'failed', 'recovery_required': True},
        'recent_errors': [],
    }
    monkeypatch.setattr(api, 'broker', lambda action, payload=None: payload_data(action, payload))

    def payload_data(action, _payload):
        assert action == 'diagnostics.status'
        return payload

    response = client.get('/api/diagnostics', headers=owner)
    assert response.status_code == 200
    assert response.json() == payload
    assert client.get('/api/diagnostics').status_code == 401


def test_controller_diagnostics_collects_problems_and_redacts(monkeypatch):
    monkeypatch.setattr(broker, 'collect_driver_health', lambda gpus: {'devices': []})
    monkeypatch.setattr(broker, 'status', lambda: {
        'services': {'airlink-api': 'failed', 'nginx': 'active'},
        'cpu_percent': 12,
        'memory_percent': 88,
        'storage_percent': 93,
    })
    monkeypatch.setattr(broker, 'update_action', lambda action, payload: {
        'state': {'status': 'failed', 'error': 'migration failed', 'recovery_required': True},
    })
    monkeypatch.setattr(broker.subprocess, 'run', lambda *args, **kwargs: SimpleNamespace(
        stdout='2026 error password=VisibleSecret token:BearerValue\n',
    ))
    result = broker.diagnostics()
    assert result['status'] == 'problems'
    assert {item['source'] for item in result['problems']} == {'service', 'system', 'update'}
    assert 'VisibleSecret' not in result['recent_errors'][0]
    assert 'BearerValue' not in result['recent_errors'][0]
    assert result['update']['recovery_required'] is True


def test_driver_warning_is_in_diagnostics_problem_summary(monkeypatch):
    monkeypatch.setattr(broker, 'status', lambda: {'services': {}, 'cpu_percent': 0,
        'memory_percent': 0, 'storage_percent': 0, 'gpus': []})
    monkeypatch.setattr(broker, 'update_action', lambda *a: {'state': {}})
    monkeypatch.setattr(broker.subprocess, 'run', lambda *a, **kw: SimpleNamespace(stdout=''))
    snapshot = {'devices': [{'name': 'Graphics controller', 'status': 'warning',
                            'detail': 'No driver bound.'}],
                'modules': [{'name': 'other_module', 'status': 'warning', 'detail': 'Module state: going'}]}
    monkeypatch.setattr(broker, 'collect_driver_health', lambda gpus: snapshot)
    result = broker.diagnostics()
    assert result['status'] == 'problems'
    assert result['problems'][0]['source'] == 'driver'
    assert result['problems'][1]['title'] == 'other_module needs attention'
    assert result['drivers'] == snapshot
