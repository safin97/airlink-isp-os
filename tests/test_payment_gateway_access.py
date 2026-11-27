import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import select, inspect

from airlink import payments, sas4
from airlink.db import SessionLocal, engine
from airlink.models import PaymentGatewayAccess, PaymentGateway, RechargePayment, User
from test_api import user
from test_payments import CREDENTIALS, setup_checkout
from test_radius_pin import remote, checkout as radius_checkout
from test_sas4 import SETTINGS
from test_shared_payments import grant_fib


@pytest.mark.parametrize('provider', ['fib', 'fastpay'])
def test_selected_manager_only_can_start_payment_and_revocation_preserves_pending(client, owner, monkeypatch, remote, provider):
    body, creates = (radius_checkout(client, owner, monkeypatch) if provider == 'fib'
                     else setup_checkout(client, owner, monkeypatch))
    selected_id, selected = user(client, owner, 'manager', 'selected-payment-manager')
    other_id, other = user(client, owner, 'manager', 'other-payment-manager')
    for manager_id, headers in [(selected_id, selected), (other_id, other)]:
        grant_fib(client, owner, manager_id)
        client.put('/api/integrations/sas4', headers=headers, json=SETTINGS).raise_for_status()
    path = '/api/payments/gateways/' + provider
    settings = {'merchant_id': CREDENTIALS['merchant_id'], 'environment': 'production',
                'access_mode': 'selected', 'manager_ids': [selected_id]}
    saved = client.put(path, headers=owner, json=settings)
    assert saved.status_code == 200, saved.text
    assert saved.json()['manager_ids'] == [selected_id]
    assert CREDENTIALS['secret'] not in saved.text
    for headers, allowed in [(owner, True), (selected, True), (other, False)]:
        response = client.get('/api/payments/methods', headers=headers)
        method = next(row for row in response.json() if row['provider'] == provider)
        assert method['configured'] is allowed and method['allowed'] is allowed
        assert selected_id not in response.text and CREDENTIALS['merchant_id'] not in response.text
    assert client.post('/api/payments/users/7', headers=other, json=body).status_code == 403
    assert not creates
    assert client.get('/api/payments/gateways/managers', headers=other).status_code == 403
    assert client.put(path, headers=other, json=settings).status_code == 403
    started = client.post('/api/payments/users/7', headers=selected, json=body)
    assert started.status_code == 200 and len(creates) == 1
    # Removing access blocks NEW payments without abandoning an existing charge.
    client.put(path, headers=owner, json={**settings, 'manager_ids': []}).raise_for_status()
    assert client.post('/api/payments/users/7', headers=selected, json=body).json()['id'] == body['transaction_id']
    with SessionLocal() as db:
        order = db.get(RechargePayment, body['transaction_id'])
        assert payments.decoded(order.encrypted_credentials) == CREDENTIALS
    activations = []
    monkeypatch.setattr(payments, 'verify_provider_payment', lambda order: 'paid')
    monkeypatch.setattr(sas4, 'redeem_card', lambda *args: activations.append(True) or {'recharged': True})
    payments.process_pending()
    assert activations == [True]
    assert client.get('/api/payments/orders/' + body['transaction_id'], headers=selected).json()['status'] == 'completed'
    assert client.post('/api/payments/users/7', headers=selected,
                       json={**body, 'transaction_id': 'c' * 32}).status_code == 403
    assert len(creates) == 1


def test_access_validation_independent_providers_and_legacy_saves(client, owner):
    mid, manager = user(client, owner, 'manager', 'payment-manager')
    viewer_id, _ = user(client, owner, 'viewer', 'payment-viewer')
    path = '/api/payments/gateways/fib'
    data = {**CREDENTIALS, 'access_mode': 'selected', 'manager_ids': [mid]}
    client.put(path, headers=owner, json=data).raise_for_status()
    # Older clients updating credentials must not silently remove restrictions.
    client.put(path, headers=owner, json=CREDENTIALS).raise_for_status()
    listing = client.get('/api/payments/gateways', headers=owner).json()
    assert listing[0]['access_mode'] == 'selected' and listing[0]['manager_ids'] == [mid]
    for invalid in ['missing', viewer_id]:
        assert client.put(path, headers=owner, json={**data, 'manager_ids': [invalid]}).status_code == 422
    assert client.put(path, headers=owner, json={**data, 'access_mode': 'bad'}).status_code == 422
    client.put('/api/payments/gateways/fastpay', headers=owner, json=CREDENTIALS).raise_for_status()
    methods = client.get('/api/payments/methods', headers=manager).json()
    assert all(row['configured'] for row in methods)
    client.put(path, headers=owner, json={**data, 'manager_ids': []}).raise_for_status()
    methods = client.get('/api/payments/methods', headers=manager).json()
    assert methods[0]['allowed'] is False and methods[1]['configured'] is True
    client.put(path, headers=owner, json={**data, 'access_mode': 'all', 'manager_ids': []}).raise_for_status()
    assert client.get('/api/payments/methods', headers=manager).json()[0]['allowed'] is True
    with SessionLocal() as db:
        db.get(User, mid).active = False
        db.commit()
        assert payments.can_use_gateway(db, db.get(User, mid), 'fib') is False


def test_access_migration_preserves_existing_merchant(client, owner):
    client.put('/api/payments/gateways/fib', headers=owner, json=CREDENTIALS).raise_for_status()
    path = Path(__file__).resolve().parents[1] / 'database/versions/d86fa5927103_payment_gateway_access.py'
    spec = importlib.util.spec_from_file_location('gateway_access_migration', path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()
            migration.upgrade()
        assert {c['name'] for c in inspect(connection).get_columns('payment_gateway_access')} == {
            c.name for c in PaymentGatewayAccess.__table__.columns}
    with SessionLocal() as db:
        assert payments.decoded(db.scalar(select(PaymentGateway)).encrypted_credentials) == CREDENTIALS
        assert payments.gateway_access(db, 'fib') == {'access_mode': 'all', 'manager_ids': []}
