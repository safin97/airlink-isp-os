"""PIN inventory is reserved before charging and released only on confirmed failure."""
import pytest
from sqlalchemy.exc import IntegrityError
from airlink import payments, sas4
from airlink.db import SessionLocal
from airlink.models import RechargePayment, RechargeCardReservation, SavedRechargeCard
from test_api import user
from test_payments import setup_checkout, QUOTE

PIN = 'PRIVATE-RECHARGE-PIN-123'


def checkout(client, owner, monkeypatch, environment='production'):
    body, creates = setup_checkout(client, owner, monkeypatch, environment, provider='fib')
    monkeypatch.setattr(sas4, 'fetch_recharge', lambda *a, **k: {
        **QUOTE, 'methods': {'card': True, 'credit': False}, 'manager_balance': '0', 'manager_cost': None})
    card = client.post('/api/card-system', headers=owner, json={'label': '20 Mbps', 'pin': PIN, 'profile_id': 3, 'price_iqd': '2500'})
    assert card.status_code == 201, card.text
    monkeypatch.setattr(sas4, 'redeem_card', lambda *a, **k: {'recharged': True})
    body.update(card_id=card.json()['id'], expected_cost=None, card_source='saved_pin')
    return body, creates


def test_fib_automatically_recharges_reserved_pin_only_after_verified_payment(client, owner, monkeypatch):
    body, creates = checkout(client, owner, monkeypatch)
    response = client.post('/api/payments/users/7', headers=owner, json=body)
    assert response.status_code == 200, response.text
    assert response.json()['fulfillment'] == 'saved_pin'
    path = '/api/payments/orders/' + body['transaction_id']
    assert client.post(path + '/pin', headers=owner).status_code == 409
    assert client.get('/api/card-system?available=true', headers=owner).json()['total'] == 0
    assert client.post('/api/card-system/' + body['card_id'] + '/pin', headers=owner).status_code == 409
    assert client.delete('/api/card-system/' + body['card_id'], headers=owner).status_code == 409
    # A repeated browser request returns the same reservation, without another charge.
    assert client.post('/api/payments/users/7', headers=owner, json=body).status_code == 200
    assert len(creates) == 1
    monkeypatch.setattr(payments, 'verify_provider_payment', lambda row: 'paid')
    activations = []
    def redeem(connection, password, user_id, request):
        assert request.method == 'card' and request.pin == PIN
        assert request.expected_profile_id == 3 and request.expected_expiration == QUOTE['expiration']
        assert user_id == 7 and request.transaction_id == body['transaction_id']
        activations.append(request.transaction_id)
        return {'recharged': True}
    monkeypatch.setattr(sas4, 'redeem_card', redeem)
    payments.process_pending(saved_pin_only=True)
    payments.process_pending(saved_pin_only=True)
    status = client.get(path, headers=owner)
    assert status.json()['status'] == 'completed'
    assert activations == [body['transaction_id']]
    assert PIN not in status.text
    assert PIN not in client.get('/api/payments/users/7', headers=owner).text
    for _ in range(2):
        assert client.post(path + '/pin', headers=owner).status_code == 409
    assert client.get('/api/card-system', headers=owner).json()['items'][0]['state'] == 'used'
    assert client.post('/api/card-system', headers=owner, json={'pin': PIN}).status_code == 409
    with SessionLocal() as db:
        assert db.query(RechargeCardReservation).count() == 1
        assert PIN not in db.query(SavedRechargeCard).one().encrypted_pin
    _, other = user(client, owner, 'manager', 'other-pin-user')
    assert client.post(path + '/pin', headers=other).status_code == 404


@pytest.mark.parametrize('environment,status,expected', [
    ('production', 'pending', 'pending'), ('production', 'declined', 'declined'),
    ('sandbox', 'paid', 'sandbox_paid'), ('sandbox', 'declined', 'declined')])
def test_unpaid_and_sandbox_never_reveal_pin(client, owner, monkeypatch, environment, status, expected):
    body, _ = checkout(client, owner, monkeypatch, environment)
    assert client.post('/api/payments/users/7', headers=owner, json=body).status_code == 200
    monkeypatch.setattr(payments, 'verify_provider_payment', lambda row: status)
    payments.process_pending()
    path = '/api/payments/orders/' + body['transaction_id']
    assert client.get(path, headers=owner).json()['status'] == expected
    assert client.post(path + '/pin', headers=owner).status_code == 409
    assert client.get('/api/card-system?available=true', headers=owner).json()['total'] == (0 if status == 'pending' else 1)


def test_unavailable_or_reserved_card_cannot_start_charge(client, owner, monkeypatch):
    body, creates = checkout(client, owner, monkeypatch)
    assert client.post('/api/payments/users/7', headers=owner, json={**body, 'card_id': 'missing'}).status_code == 409
    assert not creates
    assert client.post('/api/payments/users/7', headers=owner, json=body).status_code == 200
    assert client.post('/api/payments/users/8', headers=owner, json={**body, 'transaction_id': 'c' * 32}).status_code == 409
    assert len(creates) == 1
    # The database also prevents two orders claiming one card, independent of application checks.
    with SessionLocal() as db:
        original = db.get(RechargePayment, body['transaction_id'])
        duplicate = RechargePayment(id='d' * 32, user_id=original.user_id, sas4_user_id=8,
            sas4_username=original.sas4_username, provider='fib', environment='production',
            encrypted_credentials=original.encrypted_credentials, status='creating', amount='2500', currency='IQD', quote={})
        db.add(duplicate)
        db.flush()
        db.add(RechargeCardReservation(card_id=body['card_id'], payment_id=duplicate.id))
        with pytest.raises(IntegrityError):
            db.flush()
        db.rollback()


def test_uncertain_creation_or_verification_keeps_card_reserved(client, owner, monkeypatch):
    body, _ = checkout(client, owner, monkeypatch)
    def fail(*a):
        raise payments.PaymentError('Provider unavailable')
    monkeypatch.setattr(payments, 'create_provider_payment', fail)
    response = client.post('/api/payments/users/7', headers=owner, json=body)
    assert response.json()['status'] == 'creation_unknown'
    assert client.get('/api/card-system?available=true', headers=owner).json()['total'] == 0
    with SessionLocal() as db:
        order = db.get(RechargePayment, body['transaction_id'])
        order.status, order.provider_id = 'pending', 'test-provider'
        db.commit()
    monkeypatch.setattr(payments, 'verify_provider_payment', fail)
    payments.process_pending()
    assert client.get('/api/card-system?available=true', headers=owner).json()['total'] == 0
    assert client.post('/api/payments/orders/' + body['transaction_id'] + '/pin', headers=owner).status_code == 409


def test_local_pin_worker_does_not_activate_legacy_orders(client, owner, monkeypatch):
    body, _ = setup_checkout(client, owner, monkeypatch)
    assert client.post('/api/payments/users/7', headers=owner, json=body).status_code == 200
    monkeypatch.setattr(payments, 'verify_provider_payment', lambda *a: pytest.fail('Legacy orders are outside local PIN worker scope'))
    payments.process_pending(saved_pin_only=True)
    assert client.get('/api/payments/orders/' + body['transaction_id'], headers=owner).json()['status'] == 'pending'


def test_reservation_migration_preserves_saved_pins(client, owner):
    import importlib.util
    from pathlib import Path
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import inspect, select
    from airlink.db import engine
    response = client.post('/api/card-system', headers=owner, json={'pin': PIN})
    assert response.status_code == 201
    card_id = response.json()['id']
    path = Path(__file__).resolve().parents[1] / 'database/versions/e39ab4817c02_fib_card_reservations.py'
    spec = importlib.util.spec_from_file_location('fib_reservation_migration', path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with engine.begin() as connection:
        migration.op = Operations(MigrationContext.configure(connection))
        migration.downgrade()
        migration.upgrade()
        assert connection.execute(select(SavedRechargeCard.id)).scalar() == card_id
        assert {c['name'] for c in inspect(connection).get_columns('recharge_card_reservations')} == {'card_id', 'payment_id'}
    assert client.post('/api/card-system/' + card_id + '/pin', headers=owner).json() == {'pin': PIN}


@pytest.mark.parametrize('selling_price,currency', [('0', 'IQD'), (None, None), ('50', 'USD')])
def test_fib_charges_card_system_price_without_sas4_price_or_currency(client, owner, monkeypatch, selling_price, currency):
    body, _ = checkout(client, owner, monkeypatch)
    monkeypatch.setattr(sas4, 'fetch_recharge', lambda *a, **k: {
        **QUOTE, 'customer_price': selling_price, 'currency': currency,
        'methods': {'card': True, 'credit': False}, 'manager_cost': None, 'manager_balance': None})
    charged = []
    def create(order):
        charged.append((order.amount, order.currency))
        return 'provider-123', {'code': 'merchant-payment-code'}
    monkeypatch.setattr(payments, 'create_provider_payment', create)
    assert client.put('/api/card-system/' + body['card_id'] + '/profile', headers=owner,
        json={'profile_id': 3, 'price_iqd': '17500.50'}).status_code == 200
    response = client.post('/api/payments/users/7', headers=owner, json={**body, 'expected_amount': '17500.50'})
    assert response.status_code == 200, response.text
    assert charged == [('17500.50', 'IQD')]
    assert response.json()['amount'] == '17500.50'
    monkeypatch.setattr(payments, 'verify_provider_payment', lambda row: 'paid')
    payments.process_pending(saved_pin_only=True)
    assert client.get('/api/payments/orders/' + body['transaction_id'], headers=owner).json()['status'] == 'completed'
    assert client.post('/api/payments/orders/' + body['transaction_id'] + '/pin', headers=owner).status_code == 409


@pytest.mark.parametrize('amount', [None, '', '0', '-1', 'NaN', 'Infinity', '1.001', '1e3', '1000000001', '2,500'])
def test_card_system_rejects_invalid_price(client, owner, monkeypatch, amount):
    body, creates = checkout(client, owner, monkeypatch)
    response = client.put('/api/card-system/' + body['card_id'] + '/profile', headers=owner,
        json={'profile_id': 3, 'price_iqd': amount})
    assert response.status_code == 422, response.text
    assert not creates
    assert client.get('/api/card-system?available=true', headers=owner).json()['total'] == 1


def test_fib_auto_selects_only_matching_profile_and_price(client, owner, monkeypatch):
    body, creates = checkout(client, owner, monkeypatch)
    for profile, price in [(4, '100'), (None, None)]:
        assert client.post('/api/card-system', headers=owner, json={
            'pin': f'other-pin-{profile}', 'profile_id': profile, 'price_iqd': price}).status_code == 201
    rows = client.get('/api/card-system?available=true&profile_id=3', headers=owner).json()
    assert [row['id'] for row in rows['items']] == [body['card_id']]
    assert rows['items'][0]['price_iqd'] == '2500'
    response = client.post('/api/payments/users/7', headers=owner, json={**body, 'card_id': None})
    assert response.status_code == 200 and response.json()['amount'] == '2500'
    with SessionLocal() as db:
        assert db.get(RechargeCardReservation, body['card_id']).payment_id == body['transaction_id']
    assert client.put('/api/card-system/' + body['card_id'] + '/profile', headers=owner,
        json={'profile_id': 4, 'price_iqd': '100'}).status_code == 409
    assert len(creates) == 1


@pytest.mark.parametrize('change', ['card_profile', 'customer_profile', 'price', 'missing_price'])
def test_fib_rechecks_profile_and_price_before_bank_request(client, owner, monkeypatch, change):
    body, creates = checkout(client, owner, monkeypatch)
    if change == 'card_profile':
        client.put('/api/card-system/' + body['card_id'] + '/profile', headers=owner,
            json={'profile_id': 4, 'price_iqd': '2500'})
    elif change == 'customer_profile':
        monkeypatch.setattr(sas4, 'fetch_recharge', lambda *a: {**QUOTE, 'profile_id': 4, 'methods': {'card': True}})
    elif change == 'price':
        client.put('/api/card-system/' + body['card_id'] + '/profile', headers=owner,
            json={'profile_id': 3, 'price_iqd': '3500'})
    else:
        body.pop('expected_amount')
    response = client.post('/api/payments/users/7', headers=owner, json=body)
    assert response.status_code == 409
    assert not creates
    with SessionLocal() as db:
        assert db.query(RechargePayment).count() == 0
        assert db.query(RechargeCardReservation).count() == 0


def test_fib_never_uses_an_unassigned_card(client, owner, monkeypatch):
    body, creates = checkout(client, owner, monkeypatch)
    client.put('/api/card-system/' + body['card_id'] + '/profile', headers=owner,
        json={'profile_id': None, 'price_iqd': None})
    response = client.post('/api/payments/users/7', headers=owner, json={**body, 'card_id': None})
    assert response.status_code == 409 and not creates
