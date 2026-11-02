from datetime import date
from types import SimpleNamespace
import json
import httpx
import pytest
from airlink import sas4, sas4_reports as reports
from test_api import user


def transport_for(monkeypatch, response, requests):
    monkeypatch.setattr(sas4, 'wire_payload', lambda value: value)
    def handler(request):
        payload = json.loads(request.content) if request.content else None
        if request.url.path.endswith('/login'):
            return httpx.Response(200, json={'token': 'test-token'})
        assert request.headers['Authorization'] == 'Bearer test-token'
        requests.append((request.url.path, payload))
        return httpx.Response(200, json=response)
    return httpx.MockTransport(handler)


def test_activation_fields_filters_pagination_and_no_secrets(monkeypatch):
    calls = []
    transport = transport_for(monkeypatch, {'data': [{'created_at': '2026-11-01',
        'user_details': {'username': 'customer', 'password': 'secret'}, 'pin': 'secret',
        'total_price': '12500.00'}], 'total': 51, 'current_page': 2, 'per_page': 25}, calls)
    result = reports.fetch_report(SimpleNamespace(username='manager'), 'password', 'activations',
        manager_id=9, page=2, search='customer', date_start=date(2026, 11, 1), date_end=date(2026, 11, 2), transport=transport)
    assert result['rows'][0]['user_details.username'] == 'customer'
    assert result['rows'][0]['total_price'] == '12500.00'
    assert 'secret' not in json.dumps(result)
    assert result['last_page'] == 3
    assert calls[0][1]['manager_id'] == 9
    assert calls[0][0].endswith('/index/activations')
    assert calls[0][1]['date_start'] == '2026-11-01' and calls[0][1]['page'] == 2


def test_money_transfer_operation_and_route(monkeypatch):
    calls = []
    transport = transport_for(monkeypatch, {'data': [{'cr_manager': 'a', 'dr_manager': 'b', 'amount': '10'}],
        'total': 1, 'per_page': 25}, calls)
    result = reports.fetch_report(SimpleNamespace(username='manager'), 'password', 'money-transfers',
                                  operation='withdrawal', manager_id=8, transport=transport)
    assert calls[0][0].endswith('/report/depodrawal')
    assert calls[0][1]['operation'] == 'withdrawal'
    assert calls[0][1]['manager_id'] == 8
    assert result['rows'][0]['cr_manager'] == 'a'


@pytest.mark.parametrize('period,bucket', [('daily', 'day'), ('monthly', 'month')])
def test_statistics_use_sas_counts_without_double_counting(monkeypatch, period, bucket):
    calls = []
    transport = transport_for(monkeypatch, {'status': 200, 'profiles': [{'id': 2, 'name': 'Fast'}],
        'data': [{bucket: 1, 'profile_id': 2, 'total': 3}, {bucket: 1, 'profile_id': None, 'total': 3}, {bucket: None, 'profile_id': None, 'total': 3}]}, calls)
    result = reports.fetch_report(SimpleNamespace(username='manager'), 'password', 'activation-statistics',
                                  period=period, year=2026, month=1, manager_id=7, transport=transport)
    assert result['rows'] == [
        {'period': '2026-01-01' if period == 'daily' else '2026-01', 'profile': 'Fast', 'activations': 3},
        {'period': '2026-01-01' if period == 'daily' else '2026-01', 'profile': 'Total', 'activations': 3},
        *([{'period': 'Total', 'profile': 'Total', 'activations': 3}] if period == 'daily' else [])]
    assert calls[0][1]['manager_id'] == 7
    assert calls[0][1]['type'] == period and calls[0][1]['month'] == 1


def test_reports_credentials_are_per_account_and_section_scoped(client, owner, monkeypatch):
    first_id, first = user(client, owner, 'manager', 'first')
    _, second = user(client, owner, 'manager', 'second')
    assert client.put('/api/integrations/sas4', headers=first,
                      json={'username': 'first-sas', 'password': 'private'}).status_code == 200
    def fetch(connection, password, *args, **kwargs):
        assert connection.user_id == first_id and password == 'private'
        return {'rows': []}
    monkeypatch.setattr(reports, 'fetch_report', fetch)
    path = '/api/integrations/sas4/reports/activations'
    assert client.get(path, headers=first).status_code == 200
    assert client.get(path, headers=second).status_code == 409
    assert client.get(path).status_code in (401,403)
    assert client.get(path+'?date_start=2026-11-03&date_end=2026-11-01',headers=first).status_code == 422
    assert client.get(path+'?operation=invalid',headers=first).status_code == 422
    assert client.get(path+'?month=13',headers=first).status_code == 422
    assert client.get('/api/integrations/sas4/reports/unknown',headers=first).status_code == 404
    assert client.put('/api/users/'+first_id+'/sections',headers=owner,json={'sections':['dashboard']}).status_code == 200
    assert client.get(path,headers=first).status_code == 403
    assert [r['id'] for r in client.get('/api/integrations/sas4/reports',headers=owner).json()] == list(reports.REPORTS)


def test_report_upstream_error_is_not_shown_as_empty(monkeypatch):
    transport = transport_for(monkeypatch, {'error': 'permission denied'}, [])
    with pytest.raises(sas4.SAS4Error):
        reports.fetch_report(SimpleNamespace(username='manager'), 'password', 'activations', transport=transport)


def test_monthly_statistics_exclude_other_months_and_annual_totals(monkeypatch):
    transport = transport_for(monkeypatch, {'status': 200, 'profiles': [{'id': 2, 'name': 'Fast'}],
        'data': [{'month': 1, 'profile_id': 2, 'total': 100},
                 {'month': 2, 'profile_id': 2, 'total': 7},
                 {'month': 2, 'profile_id': None, 'total': 7},
                 {'month': None, 'profile_id': None, 'total': 107}]}, [])
    result = reports.fetch_report(SimpleNamespace(username='manager'), 'password', 'activation-statistics',
                                  period='monthly', year=2026, month=2, transport=transport)
    assert result['total'] == 2
    assert all(row['period'] == '2026-02' and row['activations'] == 7 for row in result['rows'])


def test_manager_options_are_read_only_and_sanitized(monkeypatch):
    calls = []
    transport = transport_for(monkeypatch, {'data': [
        {'id': 3, 'username': 'regional', 'password': 'private'},
        {'id': '2', 'username': 'branch', 'balance': 'private'},
        {'id': 3, 'username': 'regional'}, {'id': 0, 'username': 'invalid'}]}, calls)
    result = reports.fetch_managers(SimpleNamespace(username='manager'), 'password', transport)
    assert result == [{'id': 2, 'username': 'branch'}, {'id': 3, 'username': 'regional'}]
    assert calls == [(sas4.API_PATH + 'index/manager', None)]


def test_manager_options_use_own_connection(client, owner, monkeypatch):
    mid, manager = user(client, owner, 'manager', 'report-manager')
    path = '/api/integrations/sas4/reports/managers'
    assert client.get(path, headers=manager).status_code == 409
    client.put('/api/integrations/sas4', headers=manager, json={'username': 'sas-manager', 'password': 'private'})
    def fetch(connection, password):
        assert connection.user_id == mid and password == 'private'
        return [{'id': 2, 'username': 'branch'}]
    monkeypatch.setattr(reports, 'fetch_managers', fetch)
    assert client.get(path, headers=manager).json() == [{'id': 2, 'username': 'branch'}]
    assert client.get(path, headers=owner).status_code == 409
    assert client.get('/api/integrations/sas4/reports/activations?manager_id=0', headers=manager).status_code == 422
    client.put('/api/users/'+mid+'/sections', headers=owner, json={'sections': []})
    assert client.get(path, headers=manager).status_code == 403
