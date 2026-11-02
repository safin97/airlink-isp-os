import json
from types import SimpleNamespace
import httpx
import pytest
from airlink import payments, sas4
from airlink.db import SessionLocal
from airlink.models import PaymentGateway, RechargePayment, now
from airlink.security import cipher
from test_sas4 import SETTINGS
from test_api import user

CREDENTIALS = {'merchant_id': 'test-merchant', 'secret': 'PRIVATE-MERCHANT-SECRET'}
QUOTE = {'username': 'customer', 'profile_id': 3, 'expiration': '2026-12-01 00:00:00', 'manager_cost': '2000',
    'customer_price': '2500', 'currency': 'IQD', 'manager_balance': 'IQD 50,000', 'methods': {'credit': True}}


def encrypted():
    return cipher().encrypt(json.dumps(CREDENTIALS).encode()).decode()


def order(provider='fib', environment='production'):
    return SimpleNamespace(id='a' * 32, provider=provider, environment=environment, encrypted_credentials=encrypted(),
        amount='2500', currency='IQD', provider_id='provider-123')


def test_gateway_credentials_are_encrypted_and_scoped(client, owner):
    result = client.put('/api/payments/gateways/fib', headers=owner, json={**CREDENTIALS, 'environment': 'sandbox'})
    assert result.status_code == 200 and result.json()['configured']
    assert CREDENTIALS['secret'] not in result.text
    rows = client.get('/api/payments/gateways', headers=owner).json()
    assert CREDENTIALS['secret'] not in json.dumps(rows)
    with SessionLocal() as db:
        config = db.query(PaymentGateway).one()
        assert CREDENTIALS['secret'] not in config.encrypted_credentials
        assert payments.decoded(config.encrypted_credentials) == CREDENTIALS
    _, manager = user(client, owner, 'manager', 'other-merchant')
    assert not any(x['configured'] for x in client.get('/api/payments/gateways', headers=manager).json())
    _, viewer = user(client, owner, 'viewer', 'payment-viewer')
    assert client.get('/api/payments/gateways', headers=viewer).status_code == 403
    assert client.put('/api/payments/gateways/fib', headers=owner, json={'merchant_id': 'new-id', 'environment': 'sandbox'}).status_code == 422


@pytest.mark.parametrize('amount,currency,payment_id,success', [('2500', 'IQD', 'provider-123', True), ('2499','IQD','provider-123',False), ('2500','USD','provider-123',False), ('2500','IQD','other',False)])
def test_fib_verifies_payment_identity_amount_and_currency(amount, currency, payment_id, success):
    def handler(request):
        if request.url.path.endswith('/token'):
            assert request.url.host == 'fib.prod.fib.iq'
            return httpx.Response(200, json={'access_token': 'test-token'})
        assert request.headers['Authorization'] == 'Bearer test-token'
        return httpx.Response(200, json={'status': 'PAID', 'paymentId': payment_id, 'amount': {'amount': amount, 'currency': currency}})
    if success:
        assert payments.verify_provider_payment(order(), httpx.MockTransport(handler)) == 'paid'
    else:
        with pytest.raises(payments.PaymentError):
            payments.verify_provider_payment(order(), httpx.MockTransport(handler))


def test_fastpay_requires_validation_after_paid_status():
    paths = []
    def handler(request):
        paths.append(request.url.path)
        body = json.loads(request.content)
        assert body['orderId'] == 'a' * 32
        assert body['storeId'] == CREDENTIALS['merchant_id']
        if request.url.path.endswith('/status'):
            return httpx.Response(200, json={'code': 200, 'data': {'payment_status': 'PAID', 'merchant_order_id': 'a' * 32}})
        return httpx.Response(200, json={'code': 200, 'data': {'status': 'success', 'merchant_order_id': 'a' * 32,
            'gw_transaction_id': 'verified-provider-id', 'received_amount': 2500, 'currency': 'IQD'}})
    assert payments.verify_provider_payment(order('fastpay'), httpx.MockTransport(handler)) == 'paid'
    assert paths == ['/api/v1/public/vending/status', '/api/v1/public/vending/validate']


def setup_checkout(client, owner, monkeypatch, environment='production'):
    client.put('/api/integrations/sas4', headers=owner, json=SETTINGS)
    client.put('/api/payments/gateways/fib', headers=owner, json={**CREDENTIALS, 'environment': environment})
    monkeypatch.setattr(sas4, 'fetch_recharge', lambda *a, **k: dict(QUOTE))
    creates = []
    def create(row):
        creates.append(row.id)
        return 'provider-123', {'code': 'payment-code'}
    monkeypatch.setattr(payments, 'create_provider_payment', create)
    body = {'provider': 'fib', 'transaction_id': 'b' * 32, 'expected_amount': '2500', 'expected_cost': '2000',
        'expected_profile_id': 3, 'expected_expiration': QUOTE['expiration']}
    return body, creates


def test_checkout_is_idempotent_and_blocks_duplicate_pending_orders(client, owner, monkeypatch):
    body, creates = setup_checkout(client, owner, monkeypatch)
    first = client.post('/api/payments/users/7', headers=owner, json=body)
    assert first.status_code == 200 and first.json()['status'] == 'pending'
    assert client.post('/api/payments/users/7', headers=owner, json=body).json()['id'] == body['transaction_id']
    assert client.post('/api/payments/users/7', headers=owner, json={**body, 'transaction_id': 'c' * 32}).json()['id'] == body['transaction_id']
    assert len(creates) == 1
    _, other = user(client, owner, 'manager', 'payment-stranger')
    assert client.get('/api/payments/orders/' + body['transaction_id'], headers=other).status_code == 404
    assert client.get('/api/payments/users/7', headers=other).json() == []
    assert 'PRIVATE' not in first.text


@pytest.mark.parametrize('environment,verification,outcome', [('production','pending','pending'), ('production','paid','completed'), ('sandbox','paid','sandbox_paid'), ('production','declined','declined')])
def test_verified_payments_activate_once_and_sandbox_never_activates(client, owner, monkeypatch, environment, verification, outcome):
    body, _ = setup_checkout(client, owner, monkeypatch, environment)
    assert client.post('/api/payments/users/7', headers=owner, json=body).status_code == 200
    monkeypatch.setattr(payments, 'verify_provider_payment', lambda row: verification)
    activations = []
    def activate(connection, password, user_id, request):
        assert connection.username == SETTINGS['username'] and password == SETTINGS['password']
        assert user_id == 7 and request.method == 'credit' and request.expected_cost == '2000'
        activations.append(request.transaction_id)
        return {'recharged': True}
    monkeypatch.setattr(sas4, 'redeem_card', activate)
    payments.process_pending()
    payments.process_pending()
    result = client.get('/api/payments/orders/' + body['transaction_id'], headers=owner).json()
    assert result['status'] == outcome
    assert len(activations) == (1 if outcome == 'completed' else 0)


def test_uncertain_activation_is_not_retried(client, owner, monkeypatch):
    body, _ = setup_checkout(client, owner, monkeypatch)
    client.post('/api/payments/users/7', headers=owner, json=body)
    monkeypatch.setattr(payments, 'verify_provider_payment', lambda row: 'paid')
    activations = []
    def activate(*args):
        activations.append(True)
        raise sas4.SAS4Error('timeout')
    monkeypatch.setattr(sas4, 'redeem_card', activate)
    payments.process_pending()
    payments.process_pending()
    assert client.get('/api/payments/orders/' + body['transaction_id'], headers=owner).json()['status'] == 'paid_review'
    assert len(activations) == 1


def test_price_change_cannot_create_payment(client, owner, monkeypatch):
    body, creates = setup_checkout(client, owner, monkeypatch)
    response = client.post('/api/payments/users/7', headers=owner, json={**body, 'expected_amount': '1'})
    assert response.status_code == 409 and not creates
