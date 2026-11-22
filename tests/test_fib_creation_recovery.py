"""Separate failed authentication from an uncertain submitted charge."""
import httpx
import pytest
from airlink import payments
from airlink.db import SessionLocal
from airlink.models import RechargePayment, RechargeCardReservation
from test_fib_cards import checkout
from test_api import user


@pytest.mark.parametrize('failure,expected', [
    ('auth_401', 'creation_failed'), ('auth_timeout', 'creation_failed'),
    ('auth_bad_json', 'creation_failed'), ('auth_missing_token', 'creation_failed'),
    ('create_400', 'creation_failed'), ('create_401', 'creation_failed'),
    ('create_connect', 'creation_failed'), ('create_connect_timeout', 'creation_failed'),
    ('create_read_timeout', 'creation_unknown'), ('create_write_timeout', 'creation_unknown'),
    ('create_500', 'creation_unknown'), ('create_408', 'creation_unknown'),
    ('create_bad_json', 'creation_unknown'),
])
def test_failed_creation_releases_card_only_when_no_payment_was_submitted(client, owner, monkeypatch, failure, expected):
    real_create = payments.create_provider_payment
    body, _ = checkout(client, owner, monkeypatch)
    paths = []
    def handler(request):
        paths.append(request.url.path)
        if request.url.path.endswith('/token'):
            if failure == 'auth_401':
                return httpx.Response(401, json={'error': 'invalid_client', 'error_description': 'PRIVATE-RESPONSE-SECRET'})
            if failure == 'auth_timeout':
                raise httpx.ReadTimeout('PRIVATE-NETWORK-SECRET', request=request)
            if failure == 'auth_bad_json':
                return httpx.Response(200, content=b'not-json')
            if failure == 'auth_missing_token':
                return httpx.Response(200, json={})
            return httpx.Response(200, json={'access_token': 'PRIVATE-TOKEN'})
        if failure in ('create_connect', 'create_connect_timeout', 'create_read_timeout', 'create_write_timeout'):
            error = {'create_connect': httpx.ConnectError, 'create_connect_timeout': httpx.ConnectTimeout,
                'create_read_timeout': httpx.ReadTimeout, 'create_write_timeout': httpx.WriteTimeout}[failure]
            raise error('PRIVATE-NETWORK-SECRET', request=request)
        if failure == 'create_bad_json':
            return httpx.Response(201, content=b'not-json')
        return httpx.Response(int(failure.split('_')[-1]), json={'error': 'PRIVATE-RESPONSE-SECRET'})
    monkeypatch.setattr(payments, 'create_provider_payment', lambda row: real_create(row, httpx.MockTransport(handler)))
    response = client.post('/api/payments/users/7', headers=owner, json=body)
    assert response.status_code == 200
    assert response.json()['status'] == expected
    assert 'PRIVATE' not in response.text
    if failure.startswith('auth_'):
        assert len(paths) == 1
    with SessionLocal() as db:
        assert db.query(RechargeCardReservation).count() == (expected == 'creation_unknown')
    # Replay of the same transaction never submits it a second time.
    count = len(paths)
    assert client.post('/api/payments/users/7', headers=owner, json=body).json()['status'] == expected
    assert len(paths) == count
    monkeypatch.setattr(payments, 'create_provider_payment', lambda row: ('new-bank-id', {'code': 'new-code'}))
    retry = client.post('/api/payments/users/7', headers=owner, json={**body, 'transaction_id': 'c' * 32})
    assert retry.json()['status'] == ('pending' if expected == 'creation_failed' else 'creation_unknown')


@pytest.mark.parametrize('http_status,success', [(200, True), (401, False), (503, False)])
def test_connection_test_never_creates_payment_or_reveals_credentials(client, owner, monkeypatch, http_status, success):
    checkout(client, owner, monkeypatch)
    paths = []
    real_session = payments.provider_session
    def handler(request):
        paths.append(request.url.path)
        if request.url.path.endswith('/status'):
            assert request.method == 'GET'
            assert request.headers['Authorization'] == 'Bearer PRIVATE-TOKEN'
            return httpx.Response(404)
        assert request.url.path.endswith('/token')
        return httpx.Response(http_status, json={'access_token': 'PRIVATE-TOKEN', 'error': 'invalid_client', 'description': 'PRIVATE-SECRET'})
    monkeypatch.setattr(payments, 'provider_session', lambda: real_session(httpx.MockTransport(handler)))
    result = client.post('/api/payments/gateways/fib/test', headers=owner)
    assert result.status_code == 200 and result.json()['authenticated'] is success
    assert result.json()['payment_api_access'] is success
    assert 'PRIVATE' not in result.text
    assert len(paths) == (2 if success else 1)
    with SessionLocal() as db:
        assert db.query(RechargePayment).count() == 0
        assert db.query(RechargeCardReservation).count() == 0
    _, manager = user(client, owner, 'manager', 'fib-test-manager')
    assert client.post('/api/payments/gateways/fib/test', headers=manager).status_code == 403
    assert len(paths) == (2 if success else 1)


def test_legacy_unknown_requires_explicit_owner_review_before_retry(client, owner, monkeypatch):
    body, _ = checkout(client, owner, monkeypatch)
    def uncertain(row):
        raise payments.PaymentError('Unknown bank response')
    monkeypatch.setattr(payments, 'create_provider_payment', uncertain)
    created = client.post('/api/payments/users/7', headers=owner, json=body).json()
    assert created['can_review_creation'] is True
    path = '/api/payments/orders/' + body['transaction_id'] + '/review-creation'
    assert client.post(path, headers=owner, json={}).status_code == 422
    assert client.post(path, headers=owner, json={'confirmed_not_created': False}).status_code == 422
    _, other = user(client, owner, 'owner', 'other-payment-owner')
    assert client.post(path, headers=other, json={'confirmed_not_created': True}).status_code == 404
    with SessionLocal() as db:
        assert db.query(RechargeCardReservation).count() == 1
    result = client.post(path, headers=owner, json={'confirmed_not_created': True})
    assert result.status_code == 200
    assert result.json()['status'] == 'creation_failed'
    assert result.json()['can_review_creation'] is False
    with SessionLocal() as db:
        assert db.query(RechargeCardReservation).count() == 0
    assert client.post(path, headers=owner, json={'confirmed_not_created': True}).status_code == 409


@pytest.mark.parametrize('status,provider_id', [('pending', 'bank-id'), ('pin_ready', 'bank-id'), ('creation_unknown', 'bank-id')])
def test_review_cannot_release_a_known_payment(client, owner, monkeypatch, status, provider_id):
    body, _ = checkout(client, owner, monkeypatch)
    client.post('/api/payments/users/7', headers=owner, json=body)
    with SessionLocal() as db:
        order = db.get(RechargePayment, body['transaction_id'])
        order.status, order.provider_id = status, provider_id
        db.commit()
    response = client.post('/api/payments/orders/' + body['transaction_id'] + '/review-creation', headers=owner,
        json={'confirmed_not_created': True})
    assert response.status_code == 409
    with SessionLocal() as db:
        assert db.query(RechargeCardReservation).count() == 1


@pytest.mark.parametrize('status', [401, 403, 500, 'timeout'])
def test_connection_check_does_not_claim_success_when_token_fails_payment_api(client, owner, monkeypatch, status):
    checkout(client, owner, monkeypatch, environment='sandbox')
    real_session = payments.provider_session
    def handler(request):
        assert request.url.host == 'fib-stage.fib.iq'
        if request.url.path.endswith('/token'):
            return httpx.Response(200, json={'access_token': 'PRIVATE-TOKEN'})
        assert request.method == 'GET'
        if status == 'timeout':
            raise httpx.ReadTimeout('unavailable', request=request)
        return httpx.Response(status)
    monkeypatch.setattr(payments, 'provider_session', lambda: real_session(httpx.MockTransport(handler)))
    result = client.post('/api/payments/gateways/fib/test', headers=owner).json()
    assert result['authenticated'] is True
    assert result['payment_api_access'] is False
    assert 'No payment was created.' in result['detail']
    assert 'PRIVATE-TOKEN' not in result['detail']
