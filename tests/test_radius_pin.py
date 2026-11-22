"""SAS4 PIN checkout: live eligibility, amount integrity, holds and exactly-once use."""
from contextlib import contextmanager
from types import SimpleNamespace
import json
import httpx
import pytest
from sqlalchemy.exc import IntegrityError
from airlink import sas4, payments, radius_pin
from airlink.db import SessionLocal
from airlink.models import RadiusCardReservation, RechargePayment
from test_payments import setup_checkout, QUOTE

PIN = 'PRIVATE-RADIUS-PIN'


@pytest.fixture
def remote(monkeypatch):
    state = {
        'currency': 'IQD',
        'permissions': ['prm_cards_index', 'prm_cards_download', 'prm_users_activate', 'prm_users_activate_card'],
        'series': {'series': 'SERIES-1', 'profile_id': 3, 'type': 0, 'suspended': 0,
                   'qty': 2, 'used': 0, 'value': '25000.000', 'expiration': '2099-12-31'},
        'card': {'id': 42, 'pin': PIN, 'used_at': None, 'user_id': None, 'manager_id': None},
        'calls': [],
    }
    monkeypatch.setattr(sas4, 'wire_payload', lambda data: data)
    @contextmanager
    def session(connection, password):
        def handler(request):
            path = request.url.path.removeprefix(sas4.API_PATH)
            body = json.loads(request.content) if request.content else None
            state['calls'].append((path, body))
            if path == 'auth': data = {'permissions': state['permissions']}
            elif path == 'resources/login': data = {'data': {'site_currency': state['currency']}}
            elif path == 'index/series': data = {'data': [state['series']], 'total': 1, 'per_page': 100, 'current_page': body['page']}
            elif path == 'index/card/SERIES-1': data = {'data': [state['card']], 'total': 1, 'per_page': 100, 'current_page': body['page']}
            else: pytest.fail('Unexpected remote call: ' + path)
            return httpx.Response(200, json=data)
        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            yield client, {}
    monkeypatch.setattr(sas4, 'sas4_session', session)
    return state


def checkout(client, owner, monkeypatch):
    body, creates = setup_checkout(client, owner, monkeypatch, provider='fib')
    monkeypatch.setattr(sas4, 'fetch_recharge', lambda *a, **k: {**QUOTE, 'methods': {'card': True}, 'manager_cost': None})
    body.update(expected_amount='25000', radius_card_id=42, radius_series='SERIES-1')
    return body, creates


def test_quote_uses_sas4_value_hides_pin_and_creates_nothing(client, owner, monkeypatch, remote):
    _, creates = checkout(client, owner, monkeypatch)
    response = client.get('/api/payments/users/7/radius-card', headers=owner)
    assert response.status_code == 200, response.text
    assert response.json()['items'][0]['price_iqd'] == '25000.000'
    assert PIN not in response.text and not creates
    with SessionLocal() as db:
        assert db.query(RadiusCardReservation).count() == 0
        assert db.query(RechargePayment).count() == 0


@pytest.mark.parametrize('field,value', [('used_at', '2026-01-01'), ('user_id', 8), ('manager_id', 7), ('pin', ''), ('id', -1)])
def test_used_or_invalid_pin_never_creates_payment(client, owner, monkeypatch, remote, field, value):
    body, creates = checkout(client, owner, monkeypatch)
    remote['card'][field] = value
    assert client.post('/api/payments/users/7', headers=owner, json=body).status_code == 409
    assert not creates


@pytest.mark.parametrize('field,value', [('suspended', 1), ('profile_id', 9), ('type', 1), ('expiration', '2000-01-01'), ('value', '0'), ('qty', 0)])
def test_ineligible_series_never_creates_payment(client, owner, monkeypatch, remote, field, value):
    body, creates = checkout(client, owner, monkeypatch)
    remote['series'][field] = value
    assert client.post('/api/payments/users/7', headers=owner, json=body).status_code == 409
    assert not creates


def test_changed_price_currency_and_missing_permission_block_charge(client, owner, monkeypatch, remote):
    body, creates = checkout(client, owner, monkeypatch)
    assert client.post('/api/payments/users/7', headers=owner, json={**body, 'expected_amount': '1'}).status_code == 409
    remote['currency'] = 'USD'
    assert client.post('/api/payments/users/7', headers=owner, json=body).status_code == 409
    remote['currency'] = 'IQD'
    remote['permissions'].remove('prm_cards_download')
    assert client.post('/api/payments/users/7', headers=owner, json=body).status_code == 403
    assert not creates


def test_pin_held_before_bank_and_used_once_only_after_verified_payment(client, owner, monkeypatch, remote):
    body, _ = checkout(client, owner, monkeypatch)
    def create(order):
        with SessionLocal() as db:
            hold = db.query(RadiusCardReservation).one()
            assert hold.payment_id == order.id and PIN not in hold.encrypted_pin
            assert order.amount == '25000.000'
        return 'bank-id', {'code': 'payment-code'}
    monkeypatch.setattr(payments, 'create_provider_payment', create)
    response = client.post('/api/payments/users/7', headers=owner, json=body)
    assert response.status_code == 200, response.text
    assert response.json()['fulfillment'] == 'radius_pin' and PIN not in response.text
    assert client.get('/api/payments/users/8/radius-card', headers=owner).json()['items'] == []
    assert client.post('/api/payments/users/8', headers=owner, json={**body, 'transaction_id': 'b'*32}).status_code == 409
    activated = []
    monkeypatch.setattr(payments, 'verify_provider_payment', lambda order: 'pending')
    def redeem(connection, password, user_id, request):
        assert user_id == 7 and request.method == 'card' and request.pin == PIN
        assert request.expected_profile_id == 3 and request.expected_expiration == QUOTE['expiration']
        with SessionLocal() as db: assert db.get(RechargePayment, body['transaction_id']).status == 'activating'
        activated.append(request.transaction_id)
        return {'recharged': True}
    monkeypatch.setattr(sas4, 'redeem_card', redeem)
    payments.process_pending(saved_pin_only=True)
    assert not activated
    monkeypatch.setattr(payments, 'verify_provider_payment', lambda order: 'paid')
    for _ in range(2): payments.process_pending(saved_pin_only=True)
    response = client.get('/api/payments/orders/'+body['transaction_id'], headers=owner)
    assert response.json()['status'] == 'completed' and PIN not in response.text
    assert activated == [body['transaction_id']]
    assert client.post('/api/payments/orders/'+body['transaction_id']+'/pin', headers=owner).status_code == 409
    with SessionLocal() as db: assert db.query(RadiusCardReservation).count() == 1


@pytest.mark.parametrize('change', ['used', 'value', 'pin', 'timeout'])
def test_paid_changed_or_uncertain_card_requires_review_not_retry(client, owner, monkeypatch, remote, change):
    body, _ = checkout(client, owner, monkeypatch)
    assert client.post('/api/payments/users/7', headers=owner, json=body).status_code == 200
    monkeypatch.setattr(payments, 'verify_provider_payment', lambda order: 'paid')
    calls = []
    def redeem(*args):
        calls.append(1)
        raise sas4.SAS4Error('Uncertain activation')
    monkeypatch.setattr(sas4, 'redeem_card', redeem)
    if change == 'used': remote['card']['used_at'] = '2026-11-22'
    if change == 'value': remote['series']['value'] = '30000'
    if change == 'pin': remote['card']['pin'] = 'DIFFERENT-PIN'
    for _ in range(2): payments.process_pending(saved_pin_only=True)
    assert len(calls) == (1 if change == 'timeout' else 0)
    response = client.get('/api/payments/orders/'+body['transaction_id'], headers=owner)
    assert response.json()['status'] == 'paid_review'
    with SessionLocal() as db: assert db.query(RadiusCardReservation).count() == 1


@pytest.mark.parametrize('outcome', ['declined', 'expired', 'sandbox', 'creation_failed', 'creation_unknown'])
def test_releases_only_on_confirmed_failure_or_sandbox(client, owner, monkeypatch, remote, outcome):
    body, _ = checkout(client, owner, monkeypatch)
    if outcome.startswith('creation_'):
        def fail(order):
            if outcome == 'creation_failed': raise payments.PaymentNotCreated('Rejected')
            raise payments.PaymentError('Uncertain')
        monkeypatch.setattr(payments, 'create_provider_payment', fail)
    assert client.post('/api/payments/users/7', headers=owner, json=body).status_code == 200
    if outcome == 'sandbox':
        with SessionLocal() as db:
            db.get(RechargePayment, body['transaction_id']).environment = 'sandbox'
            db.commit()
    monkeypatch.setattr(payments, 'verify_provider_payment', lambda row: 'paid' if outcome == 'sandbox' else outcome)
    monkeypatch.setattr(sas4, 'redeem_card', lambda *a: pytest.fail('Must not redeem'))
    payments.process_pending(saved_pin_only=True)
    with SessionLocal() as db:
        assert db.query(RadiusCardReservation).count() == (1 if outcome == 'creation_unknown' else 0)


def test_remote_card_hold_is_unique_even_if_selection_races(client, owner, monkeypatch, remote):
    body, creates = checkout(client, owner, monkeypatch)
    candidate = {'id': '42', 'series': 'SERIES-1', 'label': 'Series', 'profile_id': 3, 'price_iqd': '25000', 'pin': PIN}
    monkeypatch.setattr(radius_pin, 'find_card', lambda *a, **k: candidate)
    assert client.post('/api/payments/users/7', headers=owner, json=body).status_code == 200
    assert client.post('/api/payments/users/8', headers=owner, json={**body, 'transaction_id': 'b'*32}).status_code == 409
    assert len(creates) == 1


def test_owner_review_releases_radius_hold_after_confirmed_no_payment(client, owner, monkeypatch, remote):
    body, _ = checkout(client, owner, monkeypatch)
    def uncertain(order): raise payments.PaymentError('Uncertain')
    monkeypatch.setattr(payments, 'create_provider_payment', uncertain)
    assert client.post('/api/payments/users/7', headers=owner, json=body).status_code == 200
    path = '/api/payments/orders/' + body['transaction_id'] + '/review-creation'
    assert client.post(path, headers=owner, json={'confirmed_not_created': False}).status_code == 422
    assert client.post(path, headers=owner, json={'confirmed_not_created': True}).status_code == 200
    with SessionLocal() as db: assert db.query(RadiusCardReservation).count() == 0


def test_inventory_scan_reaches_unused_pin_on_later_page(client, owner, monkeypatch):
    calls = []
    monkeypatch.setattr(sas4, 'wire_payload', lambda body: body)
    def handler(request):
        body = json.loads(request.content)
        calls.append(body['page'])
        return httpx.Response(200, json={'data': [{'id': body['page']}], 'current_page': body['page'], 'per_page': 1, 'total': 2})
    with httpx.Client(transport=httpx.MockTransport(handler)) as remote:
        assert list(radius_pin.rows(remote, {}, 'index/card/SERIES-1', {}, [12])) == [{'id': 1}, {'id': 2}]
    assert calls == [1, 2]


def test_radius_migration_preserves_existing_orders(client, owner, monkeypatch):
    import importlib.util
    from pathlib import Path
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import inspect
    from airlink.db import engine
    from test_fib_cards import checkout as legacy_checkout
    body, _ = legacy_checkout(client, owner, monkeypatch)
    assert client.post('/api/payments/users/7', headers=owner, json=body).status_code == 200
    path = Path(__file__).resolve().parents[1] / 'database/versions/a97cd6038e14_radius_card_reservations.py'
    spec = importlib.util.spec_from_file_location('radius_migration', path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with engine.begin() as connection:
        migration.op = Operations(MigrationContext.configure(connection))
        migration.downgrade()
        assert 'radius_card_reservations' not in inspect(connection).get_table_names()
        migration.upgrade()
        assert 'radius_card_reservations' in inspect(connection).get_table_names()
    with SessionLocal() as db:
        assert db.get(RechargePayment, body['transaction_id']).status == 'pending'


@pytest.mark.parametrize('used_count',[None,''])
def test_blank_series_count_checks_pin_itself_and_still_rejects_used_cards(client,owner,monkeypatch,remote,used_count):
    _,creates=checkout(client,owner,monkeypatch)
    remote['series']['used']=used_count
    response=client.get('/api/payments/users/7/radius-card',headers=owner)
    assert response.status_code==200
    assert response.json()['items'][0]['id']=='42'
    assert PIN not in response.text and not creates
    remote['card']['used_at']='2026-11-22'
    response=client.get('/api/payments/users/7/radius-card',headers=owner)
    assert response.status_code==200 and response.json()['items']==[]
    assert not creates
