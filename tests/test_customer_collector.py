import threading
from types import SimpleNamespace
from airlink import customer_collector as collector, sas4
from airlink.customer_probes import ProbeService
from test_api import user


def setup_collector(client, owner, monkeypatch):
    client.put('/api/integrations/sas4', headers=owner, json={'username': 'reader', 'password': 'test-password'}).raise_for_status()
    client.put('/api/integrations/sas4/device-access', headers=owner, json={'api_username':'device-reader','api_password':'device-password'}).raise_for_status()
    probes = ProbeService()
    probes.pool = SimpleNamespace(submit=lambda *args: None)
    monkeypatch.setattr(collector, 'probes', probes)
    return collector.CustomerCollector(), probes


def test_collects_every_page_without_browser_requests(client, owner, monkeypatch):
    service, probes = setup_collector(client, owner, monkeypatch)
    calls = []
    def fetch(connection, password, page, count, online):
        assert password == 'test-password' and count == 7 and online
        calls.append(page)
        return {'last_page': 2, 'clients': [{'username': f'user-{page}', 'session_id': page,
                                           'ip_address': f'192.168.1.{page}'}]}
    monkeypatch.setattr(sas4, 'fetch_clients', fetch)
    for _ in range(3):
        service.poll_once()
    assert calls == [1, 2, 1]
    assert len(probes.pending) == 2
    probes.pending.update(('busy', n) for n in range(32))
    service.poll_once()
    assert calls == [1, 2, 1]


def test_disabled_or_denied_accounts_are_not_collected(client, owner, monkeypatch):
    service, probes = setup_collector(client, owner, monkeypatch)
    client.put('/api/integrations/sas4/device-access', headers=owner, json={'enabled': False}).raise_for_status()
    manager_id, manager = user(client, owner, 'manager', 'collector-manager')
    client.put('/api/integrations/sas4', headers=manager, json={'username': 'manager-reader', 'password': 'test-password'}).raise_for_status()
    client.put('/api/users/'+manager_id+'/sections', headers=owner, json={'sections': ['towers']}).raise_for_status()
    calls = []
    monkeypatch.setattr(sas4, 'fetch_clients', lambda *args, **kwargs: calls.append(kwargs))
    for _ in range(3):
        service.poll_once()
    assert calls == [] and probes.pending == set()


def test_upstream_failure_backs_off_and_keeps_page(client, owner, monkeypatch):
    service, _ = setup_collector(client, owner, monkeypatch)
    calls = []
    def fetch(*args, **kwargs):
        calls.append(kwargs['page'])
        raise sas4.SAS4Error('unavailable')
    monkeypatch.setattr(sas4, 'fetch_clients', fetch)
    service.poll_once()
    service.poll_once()
    assert calls == [1] and service.pages == {}
    service.retry_at.clear()
    service.poll_once()
    assert calls == [1, 1]


def test_background_thread_starts_without_http_and_stops(monkeypatch):
    service = collector.CustomerCollector()
    called = threading.Event()
    monkeypatch.setattr(service, 'poll_once', called.set)
    service.start()
    try:
        assert called.wait(1)
        thread = service.thread
        service.start()
        assert service.thread is thread
    finally:
        service.stop()
        service.thread.join(1)
    assert not service.thread.is_alive()
