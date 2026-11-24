from airlink import payments, sas4
from test_api import user
from test_sas4 import SETTINGS
from test_radius_pin import remote, checkout


def test_owner_grants_fib_recharge_separately_from_isp_card(client, owner, monkeypatch, remote):
    body, creates = checkout(client, owner, monkeypatch)
    actor_id, manager = user(client, owner, 'manager', 'fib-permission-staff')
    assert client.put('/api/integrations/sas4', headers=manager, json=SETTINGS).status_code == 200
    assert client.post('/api/payments/users/7', headers=manager, json=body).status_code == 403
    assert client.get('/api/payments/users/7/radius-card', headers=manager).status_code == 403
    assert not creates
    # A visibility-only legacy grant must not imply permission to charge.
    assert client.put('/api/users/' + actor_id + '/sections', headers=owner,
                      json={'sections': ['isp_card', 'fib_recharge']}).status_code == 200
    assert client.get('/api/payments/users/7/radius-card', headers=manager).status_code == 200
    assert client.post('/api/payments/users/7', headers=manager, json=body).status_code == 403
    role = {'name': 'FIB recharge staff', 'sections': ['isp_card', 'fib_recharge'],
            'editable_sections': ['isp_card'], 'deletable_sections': []}
    created = client.post('/api/access-roles', headers=owner, json=role)
    assert created.status_code == 201, created.text
    role_id = created.json()['id']
    assert client.put('/api/users/' + actor_id, headers=owner,
                      json={'username': 'fib-permission-staff', 'access_role_id': role_id}).status_code == 200
    assert client.get('/api/payments/users/7/radius-card', headers=manager).status_code == 200
    assert client.post('/api/payments/users/7', headers=manager, json=body).status_code == 403
    role['editable_sections'].append('fib_recharge')
    assert client.put('/api/access-roles/' + role_id, headers=owner, json=role).status_code == 200
    assert client.post('/api/payments/users/7', headers=manager, json=body).status_code == 200
    assert len(creates) == 1
    # Removing only the FIB grant must block activation after bank verification.
    role['editable_sections'].remove('fib_recharge')
    assert client.put('/api/access-roles/' + role_id, headers=owner, json=role).status_code == 200
    monkeypatch.setattr(payments, 'verify_provider_payment', lambda order: 'paid')
    monkeypatch.setattr(sas4, 'redeem_card', lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError('FIB grant revoked')))
    payments.process_pending()
    result = client.get('/api/payments/orders/' + body['transaction_id'], headers=manager)
    assert result.json()['status'] == 'paid_review'
    assert 'FIB recharge permission changed' in result.json()['detail']
