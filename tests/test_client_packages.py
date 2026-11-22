"""Client package checkout cannot change service before payment or replay a change."""
from contextlib import contextmanager
import json
import httpx
import pytest
from airlink import sas4, payments
from airlink.db import SessionLocal
from airlink.models import RechargePayment, RadiusCardReservation
from test_client_portal import configured, login, HEADERS
from test_payments import setup_checkout, QUOTE


@pytest.fixture
def package_checkout(client, owner, configured, monkeypatch):
    _, creates = setup_checkout(client, owner, monkeypatch, provider='fib')
    state = {'profile_id': 3, 'expiration': QUOTE['expiration'], 'stock': True,
             'permissions': ['prm_users_activate', 'prm_users_activate_card', 'prm_cards_index',
                 'prm_cards_download', 'prm_users_change_profile', 'prm_users_change_profile_active'],
             'changes': [], 'activations': [], 'timeout': False}
    monkeypatch.setattr(sas4, 'wire_payload', lambda data: data)
    monkeypatch.setattr(sas4, 'fetch_recharge', lambda *a, **k: {**QUOTE, 'profile_id': state['profile_id'],
        'expiration': state['expiration'], 'methods': {'card': True}, 'transaction_id': 'a'*32})
    @contextmanager
    def session(connection, password, transport=None):
        def handler(request):
            path = request.url.path.removeprefix(sas4.API_PATH)
            body = json.loads(request.content) if request.content else None
            if path == 'auth': data = {'permissions': state['permissions']}
            elif path == 'resources/login': data = {'data': {'site_currency': 'IQD'}}
            elif path == 'list/profile/0': data = {'data': [{'id': 3, 'name': 'AirLink Basic'}, {'id': 98, 'name': 'AirLink Plus'}, {'id': 999, 'name': 'Internal-only'}]}
            elif path == 'user/7': data = {'status': 200, 'data': {'id': 7, 'profile_id': state['profile_id'], 'expiration': state['expiration'], 'status': {'expiration': True}}}
            elif path == 'index/series': data = {'data': [{'series': 'PLUS', 'profile_id': 98, 'type': 0, 'suspended': 0,
                'qty': 1, 'used': 0 if state['stock'] else 1, 'value': '25000', 'expiration': '2099-12-31'}], 'total': 1, 'per_page': 100, 'current_page': body['page']}
            elif path == 'index/card/PLUS': data = {'data': [{'id': 42, 'pin': 'PRIVATE-PIN', 'used_at': None, 'user_id': None, 'manager_id': None}], 'total': 1, 'per_page': 100, 'current_page': body['page']}
            elif path == 'user/changeProfile':
                assert body == {'user_id': 7, 'profile_id': 98, 'change_type': 'immediate'}
                state['changes'].append(body)
                state['profile_id'] = 98
                state['expiration'] = '2026-12-02 00:00:00'
                if state['timeout']: raise httpx.ReadTimeout('uncertain', request=request)
                data = {'status': 200}
            else: pytest.fail('Unexpected SAS4 call: ' + path)
            return httpx.Response(200, json=data)
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            yield client, {}
    monkeypatch.setattr(sas4, 'sas4_session', session)
    def redeem(connection, password, customer_id, data):
        assert customer_id == 7 and data.pin == 'PRIVATE-PIN'
        assert data.expected_profile_id == state['profile_id'] == 98
        assert data.expected_expiration == state['expiration']
        state['activations'].append(data.transaction_id)
        return {'recharged': True}
    monkeypatch.setattr(sas4, 'redeem_card', redeem)
    login(client)
    body = {'transaction_id': 'a'*32, 'expected_profile_id': 3, 'expected_expiration': QUOTE['expiration'],
            'expected_amount': '25000', 'radius_card_id': 42, 'radius_series': 'PLUS', 'package_profile_id': 98}
    return state, creates, body


def test_selected_quote_is_private_read_only_and_targets_the_selected_package(client, package_checkout):
    state, creates, _ = package_checkout
    response = client.get('/api/client/fib-quote?package_profile_id=98')
    assert response.status_code == 200, response.text
    assert response.json()['items'][0]['profile_id'] == 98
    assert response.json()['package']['name'] == 'AirLink Plus'
    assert 'PRIVATE-PIN' not in response.text
    assert not creates and not state['changes'] and state['profile_id'] == 3
    with SessionLocal() as db: assert db.query(RadiusCardReservation).count() == 0


@pytest.mark.parametrize('verification', ['pending', 'declined', 'expired', 'paid_review'])
def test_unpaid_or_unverified_package_never_changes_service(client, package_checkout, monkeypatch, verification):
    state, creates, body = package_checkout
    response = client.post('/api/client/payments', headers=HEADERS, json=body)
    assert response.status_code == 200, response.text
    assert response.json()['profile_id'] == 98
    assert state['profile_id'] == 3 and len(creates) == 1
    monkeypatch.setattr(payments, 'verify_provider_payment', lambda row: verification)
    payments.process_pending(saved_pin_only=True)
    assert not state['changes'] and not state['activations']


def test_paid_package_changes_then_recharges_once(client, package_checkout, monkeypatch):
    state, creates, body = package_checkout
    assert client.post('/api/client/payments', headers=HEADERS, json=body).status_code == 200
    assert client.post('/api/client/payments', headers=HEADERS, json=body).status_code == 200
    assert len(creates) == 1 and not state['changes']
    monkeypatch.setattr(payments, 'verify_provider_payment', lambda row: 'paid')
    for _ in range(3): payments.process_pending(saved_pin_only=True)
    assert len(state['changes']) == 1 and state['activations'] == [body['transaction_id']], state
    response = client.get('/api/client/payments/' + body['transaction_id'])
    assert response.json()['status'] == 'completed'
    assert response.json()['profile'] == 'AirLink Plus' and 'PRIVATE' not in response.text


@pytest.mark.parametrize('problem', ['empty', 'price', 'permission', 'unlisted', 'other_customer'])
def test_invalid_package_purchase_never_contacts_bank(client, package_checkout, problem):
    state, creates, body = package_checkout
    if problem == 'empty': state['stock'] = False
    if problem == 'price': body['expected_amount'] = '1'
    if problem == 'permission': state['permissions'].remove('prm_users_change_profile_active')
    if problem == 'unlisted': body['package_profile_id'] = 999
    if problem == 'other_customer': body['user_id'] = 8
    response = client.post('/api/client/payments', headers=HEADERS, json=body)
    assert response.status_code in (403, 409, 422), response.text
    assert not creates and not state['changes']


@pytest.mark.parametrize('problem', ['timeout', 'account_changed', 'stock_changed', 'sandbox'])
def test_paid_change_failures_are_not_replayed(client, package_checkout, monkeypatch, problem):
    state, _, body = package_checkout
    assert client.post('/api/client/payments', headers=HEADERS, json=body).status_code == 200
    if problem == 'timeout': state['timeout'] = True
    if problem == 'account_changed': state['expiration'] = '2027-01-01'
    if problem == 'stock_changed': state['stock'] = False
    if problem == 'sandbox':
        with SessionLocal() as db:
            db.get(RechargePayment, body['transaction_id']).environment = 'sandbox'
            db.commit()
    monkeypatch.setattr(payments, 'verify_provider_payment', lambda row: 'paid')
    for _ in range(3): payments.process_pending(saved_pin_only=True)
    assert len(state['changes']) == (1 if problem == 'timeout' else 0)
    assert not state['activations']
    assert client.get('/api/client/payments/' + body['transaction_id']).json()['status'] == ('sandbox_paid' if problem == 'sandbox' else 'paid_review')


def test_buying_current_package_recharges_without_changing_profile(client, package_checkout, monkeypatch):
    state, _, body = package_checkout
    state['profile_id'] = body['expected_profile_id'] = 98
    state['permissions'].remove('prm_users_change_profile_active')
    assert client.post('/api/client/payments', headers=HEADERS, json=body).status_code == 200
    monkeypatch.setattr(payments, 'verify_provider_payment', lambda row: 'paid')
    payments.process_pending(saved_pin_only=True)
    assert not state['changes'] and state['activations'] == [body['transaction_id']]
    assert client.get('/api/client/payments/' + body['transaction_id']).json()['status'] == 'completed'
