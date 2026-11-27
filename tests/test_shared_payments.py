import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import select, inspect
from airlink import payments, sas4
from airlink.db import SessionLocal, engine
from airlink.models import User, PaymentGateway, SharedPaymentGateway, PaymentGatewayAccess, RechargePayment, UserSectionEdits
from test_api import user
from test_payments import CREDENTIALS, setup_checkout, encrypted
from test_sas4 import SETTINGS
from test_radius_pin import remote, checkout as radius_checkout, PIN
from airlink.section_access import OPERATIONAL


def grant_fib(client, owner, actor_id):
    sections = [*OPERATIONAL, 'fib_recharge']
    result = client.put('/api/users/' + actor_id + '/sections', headers=owner,
                        json={'sections': sections, 'editable_sections': sections, 'deletable_sections': []})
    assert result.status_code == 200, result.text


@pytest.mark.parametrize('provider', ['fib', 'fastpay'])
def test_manager_uses_owner_merchant_with_own_recharge_identity(client, owner, monkeypatch, remote, provider):
    body, _ = (radius_checkout(client, owner, monkeypatch) if provider == 'fib'
               else setup_checkout(client, owner, monkeypatch))
    manager_id, manager = user(client, owner, 'manager', 'shared-bank-manager')
    if provider == 'fib':
        grant_fib(client, owner, manager_id)
    assert client.put('/api/integrations/sas4', headers=manager,
                      json={**SETTINGS, 'username': 'manager-radius'}).status_code == 200
    methods = client.get('/api/payments/methods', headers=manager)
    assert next(item for item in methods.json() if item['provider'] == provider)['configured']
    assert CREDENTIALS['merchant_id'] not in methods.text and CREDENTIALS['secret'] not in methods.text
    assert client.get('/api/payments/gateways', headers=manager).status_code == 403
    assert client.put('/api/payments/gateways/' + provider, headers=manager, json=CREDENTIALS).status_code == 403
    if provider == 'fib':
        preview = client.get('/api/payments/users/7/radius-card', headers=manager)
        assert preview.status_code == 200 and PIN not in preview.text
        assert client.get('/api/card-system', headers=manager).status_code == 403
    created = []
    def create(order):
        assert payments.decoded(order.encrypted_credentials) == CREDENTIALS
        assert order.user_id == manager_id and order.sas4_username == 'manager-radius'
        created.append(order.id)
        return 'bank-verified-id', {'code': 'qr-code'}
    monkeypatch.setattr(payments, 'create_provider_payment', create)
    response = client.post('/api/payments/users/7', headers=manager, json=body)
    assert response.status_code == 200, response.text
    assert len(created) == 1 and CREDENTIALS['secret'] not in response.text
    assert client.get('/api/payments/orders/' + body['transaction_id'], headers=owner).status_code == 200
    _, other_staff = user(client, owner, 'manager', 'different-bank-staff')
    assert client.get('/api/payments/orders/' + body['transaction_id'], headers=other_staff).status_code == 404
    activations = []
    def activate(connection, password, customer, request):
        assert connection.username == 'manager-radius' and customer == 7
        assert request.method == ('card' if provider == 'fib' else 'credit')
        if provider == 'fib':
            assert request.pin == PIN
        activations.append(request.transaction_id)
        return {'recharged': True}
    monkeypatch.setattr(sas4, 'redeem_card', activate)
    monkeypatch.setattr(payments, 'verify_provider_payment', lambda order: 'paid')
    payments.process_pending()
    payments.process_pending()
    assert activations == [body['transaction_id']]
    assert client.get('/api/payments/orders/' + body['transaction_id'], headers=manager).json()['status'] == 'completed'


def test_existing_orders_keep_merchant_snapshot_when_owner_changes_settings(client, owner, monkeypatch):
    body, _ = setup_checkout(client, owner, monkeypatch)
    assert client.post('/api/payments/users/7', headers=owner, json=body).status_code == 200
    assert client.put('/api/payments/gateways/fastpay', headers=owner,
                      json={'merchant_id': 'new-merchant', 'secret': 'new-secret', 'environment': 'sandbox'}).status_code == 200
    with SessionLocal() as db:
        order = db.get(RechargePayment, body['transaction_id'])
        assert payments.decoded(order.encrypted_credentials) == CREDENTIALS
        assert order.environment == 'production'


def test_owner_can_review_unconfirmed_staff_payment_but_staff_cannot(client, owner, monkeypatch, remote):
    body, _ = radius_checkout(client, owner, monkeypatch)
    actor_id, manager = user(client, owner, 'manager', 'bank-review-staff')
    grant_fib(client, owner, actor_id)
    assert client.put('/api/integrations/sas4', headers=manager, json=SETTINGS).status_code == 200
    def uncertain(order):
        raise payments.PaymentError('Unconfirmed bank response')
    monkeypatch.setattr(payments, 'create_provider_payment', uncertain)
    response = client.post('/api/payments/users/7', headers=manager, json=body)
    assert response.json()['status'] == 'creation_unknown'
    path = '/api/payments/orders/' + body['transaction_id'] + '/review-creation'
    assert client.post(path, headers=manager, json={'confirmed_not_created': True}).status_code == 403
    history = client.get('/api/payments/users/7', headers=owner).json()
    assert history[0]['id'] == body['transaction_id']
    result = client.post(path, headers=owner, json={'confirmed_not_created': True})
    assert result.status_code == 200 and result.json()['status'] == 'creation_failed'


def test_staff_permission_revoked_after_charge_requires_review(client, owner, monkeypatch, remote):
    body, _ = radius_checkout(client, owner, monkeypatch)
    actor_id, manager = user(client, owner, 'manager', 'revoked-bank-staff')
    grant_fib(client, owner, actor_id)
    assert client.put('/api/integrations/sas4', headers=manager, json=SETTINGS).status_code == 200
    assert client.post('/api/payments/users/7', headers=manager, json=body).status_code == 200
    with SessionLocal() as db:
        db.get(UserSectionEdits, actor_id).sections = []
        db.commit()
    monkeypatch.setattr(payments, 'verify_provider_payment', lambda order: 'paid')
    monkeypatch.setattr(sas4, 'redeem_card', lambda *a, **k: pytest.fail('Revoked permission must not activate service'))
    payments.process_pending()
    assert client.get('/api/payments/orders/' + body['transaction_id'], headers=manager).json()['status'] == 'paid_review'


def test_selected_owner_deactivation_does_not_fall_back_to_another_merchant(client, owner):
    assert client.put('/api/payments/gateways/fib', headers=owner, json=CREDENTIALS).status_code == 200
    second_id, second = user(client, owner, 'owner', 'second-owner')
    assert client.put('/api/payments/gateways/fib', headers=second,
                      json={'merchant_id': 'second-merchant', 'secret': 'second-secret'}).status_code == 200
    assert client.get('/api/payments/gateways', headers=owner).json()[0]['merchant_id'] == 'second-merchant'
    with SessionLocal() as db:
        db.get(User, second_id).active = False
        db.commit()
    assert client.get('/api/payments/methods', headers=owner).json()[0]['configured'] is False


def test_manager_cannot_charge_without_owner_setup_or_with_removed_permission(client, owner, monkeypatch, remote):
    body, creates = radius_checkout(client, owner, monkeypatch)
    manager_id, manager = user(client, owner, 'manager', 'no-bank-setup')
    grant_fib(client, owner, manager_id)
    assert client.put('/api/integrations/sas4', headers=manager, json=SETTINGS).status_code == 200
    with SessionLocal() as db:
        db.delete(db.get(SharedPaymentGateway, 'fib'))
        db.commit()
    response = client.post('/api/payments/users/7', headers=manager, json=body)
    assert response.status_code == 409 and 'owner' in response.text
    assert not creates
    assert client.put('/api/payments/gateways/fib', headers=owner, json=CREDENTIALS).status_code == 200
    with SessionLocal() as db:
        db.get(UserSectionEdits, manager_id).sections = []
        db.commit()
    assert client.post('/api/payments/users/7', headers=manager, json=body).status_code == 403
    assert not creates


def test_migration_preserves_one_owner_bank_and_does_not_guess_between_multiple(client, owner):
    second_id, _ = user(client, owner, 'owner', 'migration-owner')
    manager_id, _ = user(client, owner, 'manager', 'legacy-manager-bank')
    with SessionLocal() as db:
        owner_id = db.scalar(select(User.id).where(User.username == 'owner'))
        for actor, provider in [(owner_id, 'fib'), (owner_id, 'fastpay'), (second_id, 'fastpay'), (manager_id, 'fib')]:
            db.add(PaymentGateway(user_id=actor, provider=provider, encrypted_credentials=encrypted()))
        db.commit()
    path = Path(__file__).resolve().parents[1] / 'database/versions/a53cd2694e70_shared_payment_gateways.py'
    spec = importlib.util.spec_from_file_location('shared_gateways_migration', path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with engine.begin() as connection:
        # Rehearse this older migration against its original schema; the later
        # access policy table references the shared gateway on PostgreSQL.
        PaymentGatewayAccess.__table__.drop(connection)
        migration.op = Operations(MigrationContext.configure(connection))
        migration.downgrade()
        migration.upgrade()
        columns = {c['name'] for c in inspect(connection).get_columns('shared_payment_gateways')}
        assert columns == {c.name for c in SharedPaymentGateway.__table__.columns}
        PaymentGatewayAccess.__table__.create(connection)
    with SessionLocal() as db:
        assert db.get(SharedPaymentGateway, 'fib').user_id == owner_id
        assert db.get(SharedPaymentGateway, 'fastpay') is None
        assert len(db.scalars(select(PaymentGateway)).all()) == 4
