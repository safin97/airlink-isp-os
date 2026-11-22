"""FIB reserves inventory before charging, then activates the PIN once."""
import pytest
from airlink import payments, sas4, customer_telegram
from airlink.db import SessionLocal
from airlink.models import RechargePayment, RechargeCardReservation, SavedRechargeCard, User
from test_fib_cards import checkout, PIN


def test_empty_card_inventory_never_contacts_bank(client, owner, monkeypatch):
    body, creates = checkout(client, owner, monkeypatch)
    assert client.delete('/api/card-system/' + body['card_id'], headers=owner).status_code == 204
    for card_id in (None, body['card_id']):
        response = client.post('/api/payments/users/7', headers=owner, json={**body, 'card_id': card_id})
        assert response.status_code == 409
    assert not creates
    with SessionLocal() as db:
        assert db.query(RechargePayment).count() == 0
        assert db.query(RechargeCardReservation).count() == 0


def test_reservation_is_committed_before_bank_creation(client, owner, monkeypatch):
    body, _ = checkout(client, owner, monkeypatch)
    def create(row):
        with SessionLocal() as db:
            assert db.get(RechargeCardReservation, body['card_id']).payment_id == row.id
            assert db.get(RechargePayment, row.id).status == 'creating'
        return 'bank-id', {'code': 'code'}
    monkeypatch.setattr(payments, 'create_provider_payment', create)
    assert client.post('/api/payments/users/7', headers=owner, json={**body, 'card_id': None}).status_code == 200


@pytest.mark.parametrize('state', ['pending', 'declined', 'expired', 'paid_review'])
def test_no_pin_activation_without_verified_timely_payment(client, owner, monkeypatch, state):
    body, _ = checkout(client, owner, monkeypatch)
    client.post('/api/payments/users/7', headers=owner, json=body)
    monkeypatch.setattr(payments, 'verify_provider_payment', lambda row: state)
    monkeypatch.setattr(sas4, 'redeem_card', lambda *a, **k: pytest.fail('No verified payment'))
    payments.process_pending(saved_pin_only=True)
    assert client.post('/api/payments/orders/' + body['transaction_id'] + '/pin', headers=owner).status_code == 409


def test_sandbox_payment_does_not_recharge_real_pin(client, owner, monkeypatch):
    body, _ = checkout(client, owner, monkeypatch, 'sandbox')
    client.post('/api/payments/users/7', headers=owner, json=body)
    monkeypatch.setattr(payments, 'verify_provider_payment', lambda row: 'paid')
    monkeypatch.setattr(sas4, 'redeem_card', lambda *a, **k: pytest.fail('Sandbox must not recharge'))
    payments.process_pending(saved_pin_only=True)
    assert client.get('/api/payments/orders/' + body['transaction_id'], headers=owner).json()['status'] == 'sandbox_paid'
    assert client.get('/api/card-system?available=true', headers=owner).json()['total'] == 1


@pytest.mark.parametrize('outcome', ['timeout', 'not_confirmed', 'receipt_failure'])
def test_automatic_pin_recharge_is_never_replayed(client, owner, monkeypatch, outcome):
    body, _ = checkout(client, owner, monkeypatch)
    client.post('/api/payments/users/7', headers=owner, json=body)
    monkeypatch.setattr(payments, 'verify_provider_payment', lambda row: 'paid')
    activations = []
    def redeem(connection, password, user_id, request):
        assert request.method == 'card' and request.pin == PIN
        with SessionLocal() as db:
            assert db.get(RechargePayment, body['transaction_id']).status == 'activating'
        activations.append(request.transaction_id)
        if outcome == 'timeout': raise sas4.SAS4Error('uncertain result')
        return {'recharged': outcome != 'not_confirmed'}
    monkeypatch.setattr(sas4, 'redeem_card', redeem)
    if outcome == 'receipt_failure':
        def fail(*a, **k): raise RuntimeError('receipt failure')
        monkeypatch.setattr(customer_telegram, 'activation', fail)
    for _ in range(3): payments.process_pending(saved_pin_only=True)
    result = client.get('/api/payments/orders/' + body['transaction_id'], headers=owner)
    assert result.json()['status'] == ('completed' if outcome == 'receipt_failure' else 'paid_review')
    assert PIN not in result.text
    assert activations == [body['transaction_id']]
    assert client.get('/api/card-system?available=true', headers=owner).json()['total'] == 0
    assert client.post('/api/payments/orders/' + body['transaction_id'] + '/pin', headers=owner).status_code == 409


def test_legacy_pin_ready_flow_remains_manual(client, owner, monkeypatch):
    body, _ = checkout(client, owner, monkeypatch)
    client.post('/api/payments/users/7', headers=owner, json=body)
    with SessionLocal() as db:
        row = db.get(RechargePayment, body['transaction_id'])
        row.quote = {k: v for k, v in row.quote.items() if k != 'auto_recharge'}
        db.commit()
    monkeypatch.setattr(payments, 'verify_provider_payment', lambda row: 'paid')
    monkeypatch.setattr(sas4, 'redeem_card', lambda *a, **k: pytest.fail('Legacy order must not auto recharge'))
    payments.process_pending(saved_pin_only=True)
    assert client.post('/api/payments/orders/' + body['transaction_id'] + '/pin', headers=owner).json() == {'pin': PIN}


@pytest.mark.parametrize('changed', ['profile', 'expiration'])
def test_auto_card_checks_service_snapshot_before_sas4_activation(monkeypatch, changed):
    import httpx
    from types import SimpleNamespace
    from test_sas4 import SETTINGS
    requests = []
    def handler(request):
        requests.append(request.url.path)
        if request.url.path.endswith('/login'):
            return httpx.Response(200, json={'token': 'token'})
        if request.url.path.endswith('/auth'):
            return httpx.Response(200, json={'permissions': ['prm_users_activate', 'prm_users_activate_card']})
        assert request.url.path.endswith('/user/7')
        return httpx.Response(200, json={'status': 200, 'data': {'id': 7, 'profile_id': 4 if changed == 'profile' else 3,
            'expiration': '2026-12-02' if changed == 'expiration' else '2026-12-01'}})
    data = sas4.CardRecharge(method='card', pin=PIN, transaction_id='a' * 32,
        expected_profile_id=3, expected_expiration='2026-12-01')
    with pytest.raises(sas4.HTTPException) as error:
        sas4.redeem_card(SimpleNamespace(**SETTINGS), SETTINGS['password'], 7, data, transport=httpx.MockTransport(handler))
    assert error.value.status_code == 409
    assert not any(path.endswith('/user/activate') for path in requests)
