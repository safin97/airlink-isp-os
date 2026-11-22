"""Bank-confirmed expiry and the five-minute PIN release boundary."""
from datetime import timedelta
import httpx
import pytest
from airlink import payments, sas4
from airlink.db import SessionLocal
from airlink.models import RechargePayment, RechargeCardReservation
from test_fib_cards import checkout
from test_payments import order


def expired_checkout(client, owner, monkeypatch):
    body, _ = checkout(client, owner, monkeypatch)
    response = client.post('/api/payments/users/7', headers=owner, json=body)
    assert response.status_code == 200
    assert payments.payment_time(response.json()['expires_at']) > payments.now()
    with SessionLocal() as db:
        row = db.get(RechargePayment, body['transaction_id'])
        row.created_at = payments.now() - timedelta(minutes=5, seconds=1)
        db.commit()
    return body, '/api/payments/orders/' + body['transaction_id']


@pytest.mark.parametrize('cancel_fails,bank_state', [(False, 'declined'), (False, 'pending'), (True, 'pending'), (True, 'expired')])
def test_expiry_releases_card_only_after_bank_confirmation(client, owner, monkeypatch, cancel_fails, bank_state):
    body, path = expired_checkout(client, owner, monkeypatch)
    states = iter(['pending', bank_state])
    monkeypatch.setattr(payments, 'verify_provider_payment', lambda row: next(states))
    cancels = []
    def cancel(row):
        cancels.append(row.id)
        if cancel_fails:
            raise httpx.ReadTimeout('cancellation outcome unknown')
    monkeypatch.setattr(payments, 'cancel_fib_payment', cancel)
    monkeypatch.setattr(sas4, 'redeem_card', lambda *a, **k: pytest.fail('An unpaid card must never recharge service'))
    payments.process_pending(saved_pin_only=True)
    assert cancels == [body['transaction_id']]
    final = client.get(path, headers=owner).json()
    confirmed = bank_state in ('declined', 'expired')
    assert final['status'] == ('expired' if confirmed else 'pending')
    assert client.post(path + '/pin', headers=owner).status_code == 409
    assert client.get('/api/card-system?available=true', headers=owner).json()['total'] == int(confirmed)
    if confirmed:
        # Even if the PIN is reserved by a new checkout, the expired order cannot reveal it.
        monkeypatch.setattr(payments, 'verify_provider_payment', lambda row: 'paid')
        payments.process_pending(saved_pin_only=True)
        assert client.post(path + '/pin', headers=owner).status_code == 409
        assert client.get(path, headers=owner).json()['status'] == 'expired'


def test_timely_payment_confirmed_after_deadline_is_not_lost(client, owner, monkeypatch):
    body, path = expired_checkout(client, owner, monkeypatch)
    states = iter(['pending', 'paid'])
    monkeypatch.setattr(payments, 'verify_provider_payment', lambda row: next(states))
    def cancellation_race(row):
        raise payments.PaymentError('Payment already completed')
    monkeypatch.setattr(payments, 'cancel_fib_payment', cancellation_race)
    payments.process_pending(saved_pin_only=True)
    assert client.get(path, headers=owner).json()['status'] == 'completed'
    with SessionLocal() as db:
        assert db.get(RechargeCardReservation, body['card_id']) is not None


@pytest.mark.parametrize('paid_offset,expected', [(-1, 'paid'), (0, 'paid'), (1, 'paid_review'), (None, 'paid_review'), ('invalid', 'paid_review')])
def test_bank_paid_timestamp_must_be_inside_window_after_deadline(paid_offset, expected):
    row = order()
    row.created_at = payments.now() - timedelta(minutes=6)
    deadline = row.created_at + timedelta(minutes=5)
    paid_at = (deadline + timedelta(seconds=paid_offset)).isoformat() if isinstance(paid_offset, int) else paid_offset
    def handler(request):
        if request.url.path.endswith('/token'):
            return httpx.Response(200, json={'access_token': 'token'})
        return httpx.Response(200, json={'paymentId': row.provider_id, 'status': 'PAID', 'paidAt': paid_at,
            'amount': {'amount': row.amount, 'currency': 'IQD'}})
    assert payments.verify_provider_payment(row, httpx.MockTransport(handler)) == expected


def test_late_or_unverifiable_payment_keeps_pin_locked(client, owner, monkeypatch):
    body, path = expired_checkout(client, owner, monkeypatch)
    monkeypatch.setattr(payments, 'verify_provider_payment', lambda row: 'paid_review')
    monkeypatch.setattr(payments, 'cancel_fib_payment', lambda row: pytest.fail('Do not cancel received funds'))
    payments.process_pending(saved_pin_only=True)
    assert client.get(path, headers=owner).json()['status'] == 'paid_review'
    assert client.post(path + '/pin', headers=owner).status_code == 409
    assert client.get('/api/card-system?available=true', headers=owner).json()['total'] == 0


def test_bank_expiration_reason_maps_to_expired():
    def handler(request):
        if request.url.path.endswith('/token'):
            return httpx.Response(200, json={'access_token': 'token'})
        return httpx.Response(200, json={'paymentId': 'provider-123', 'status': 'DECLINED', 'decliningReason': 'PAYMENT_EXPIRATION'})
    assert payments.verify_provider_payment(order(), httpx.MockTransport(handler)) == 'expired'


def test_cancellation_uses_authenticated_bank_endpoint():
    paths = []
    def handler(request):
        paths.append(request.url.path)
        if request.url.path.endswith('/token'):
            return httpx.Response(200, json={'access_token': 'token'})
        assert request.method == 'POST' and request.headers['Authorization'] == 'Bearer token'
        return httpx.Response(204)
    payments.cancel_fib_payment(order(), httpx.MockTransport(handler))
    assert paths[-1] == '/protected/v1/payments/provider-123/cancel'


def test_deadline_uses_earlier_bank_expiry():
    row = order()
    row.created_at = payments.now()
    row.checkout = {'valid_until': (row.created_at + timedelta(minutes=2)).isoformat()}
    assert payments.fib_deadline(row) == row.created_at + timedelta(minutes=2)
    row.checkout = {'valid_until': (row.created_at + timedelta(hours=8)).isoformat()}
    assert payments.fib_deadline(row) == row.created_at + timedelta(minutes=5)


def test_pending_checks_rotate_past_oldest_fifty(client, owner, monkeypatch):
    body, _ = checkout(client, owner, monkeypatch)
    client.post('/api/payments/users/7', headers=owner, json=body)
    with SessionLocal() as db:
        original = db.get(RechargePayment, body['transaction_id'])
        for i in range(50):
            db.add(RechargePayment(id=f'{i:032x}', user_id=original.user_id, sas4_user_id=100+i,
                sas4_username=original.sas4_username, provider='fib', environment='production',
                encrypted_credentials=original.encrypted_credentials, provider_id=f'bank-{i}',
                amount='2500', currency='IQD', status='pending', quote={'fulfillment': 'saved_pin'},
                created_at=original.created_at-timedelta(seconds=1), updated_at=original.updated_at-timedelta(seconds=1)))
        db.commit()
    seen = []
    def verify(row):
        seen.append(row.id)
        return 'pending'
    monkeypatch.setattr(payments, 'verify_provider_payment', verify)
    payments.process_pending(saved_pin_only=True)
    assert body['transaction_id'] not in seen
    payments.process_pending(saved_pin_only=True)
    assert body['transaction_id'] in seen
