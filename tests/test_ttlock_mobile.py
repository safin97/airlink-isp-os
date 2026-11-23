import pytest
from fastapi import HTTPException
from airlink import ttlock as t
from airlink.db import SessionLocal
from airlink.models import TTLockMobileOperation
from test_ttlock import cloud, CONFIG, PATH
from test_api import user


@pytest.fixture
def mobile_cloud(cloud, monkeypatch):
    real = t.request
    calls = []
    def request(region, path, body):
        calls.append((path, dict(body)))
        if path == '/v3/identityCard/list':
            return {'list': [{'lockId': 42, 'cardId': 7, 'cardNumber': '12345', 'cardName': 'Office card',
                'startDate': 0, 'endDate': 0, 'cardType': 1}], 'pages': 1, 'total': 1}
        if path == '/v3/identityCard/add':
            return {'cardId': 9}
        if path == '/v3/fingerprint/list':
            return {'list': [{'lockId': 42, 'fingerprintId': 7, 'fingerprintNumber': '98765',
                'fingerprintName': 'Office finger', 'startDate': 0, 'endDate': 0, 'fingerprintType': 1}], 'pages': 1, 'total': 1}
        if path == '/v3/lock/listKeyboardPwd':
            return {'list': [{'lockId': 42, 'keyboardPwdId': 7, 'keyboardPwd': '456789',
                'keyboardPwdName': 'Office code', 'startDate': 0, 'endDate': 0, 'keyboardPwdType': 2}], 'pages': 1, 'total': 1}
        if path == '/v3/fingerprint/add':
            return {'fingerprintId': 9}
        if path == '/v3/keyboardPwd/add':
            return {'keyboardPwdId': 9}
        if path == '/v3/lock/initialize':
            return {'lockId': 99, 'keyId': 100}
        return real(region, path, body)
    monkeypatch.setattr(t, 'request', request)
    return calls


def connect(client, owner):
    assert client.put(PATH, headers=owner, json=CONFIG).status_code == 200


def test_mobile_credentials_and_cards_remain_owner_scoped(client, owner, mobile_cloud):
    connect(client, owner)
    assert 'lock_data' not in client.get(PATH + '/locks', headers=owner).text
    result = client.get(PATH + '/locks/42/bluetooth', headers=owner)
    assert result.json() == {'lock_data': 'private-lock-data'}
    assert result.headers['cache-control'] == 'no-store'
    assert client.get(PATH + '/locks/99/bluetooth', headers=owner).status_code == 404
    assert client.get(PATH + '/locks/42/cards', headers=owner).json()['items'][0]['id'] == 7
    assert client.get(PATH + '/locks/99/cards', headers=owner).status_code == 404
    _, other = user(client, owner, 'owner', 'other-mobile-owner')
    assert client.get(PATH + '/locks/42/bluetooth', headers=other).status_code == 409
    _, manager = user(client, owner, 'manager', 'mobile-manager')
    for suffix in ('/locks/42/bluetooth', '/locks/42/cards', '/mobile/pending'):
        assert client.get(PATH + suffix, headers=manager).status_code == 403
        assert client.get(PATH + suffix).status_code == 401
    assert client.post(PATH + '/mobile/prepare', headers=manager, json={'request_id': 'a'*32, 'action': 'card_add', 'lock_id': 42, 'name': 'Test'}).status_code == 403


@pytest.mark.parametrize('action,extra,result,expected,type_key', [
    ('card_add', {'name': 'Test card'}, {'card_number': '123'}, '/v3/identityCard/add', 'addType'),
    ('card_delete', {'card_id': 7}, {}, '/v3/identityCard/delete', 'deleteType'),
    ('card_period', {'card_id': 7, 'start': 1000, 'end': 2000}, {}, '/v3/identityCard/changePeriod', 'changeType'),
    ('fingerprint_add', {'name': 'Test finger'}, {'fingerprint_number': '98765'}, '/v3/fingerprint/add', 'fingerprintType'),
    ('fingerprint_delete', {'card_id': 7}, {}, '/v3/fingerprint/delete', 'deleteType'),
    ('fingerprint_period', {'card_id': 7, 'start': 1000, 'end': 2000}, {}, '/v3/fingerprint/changePeriod', 'changeType'),
    ('passcode_add', {'name': 'Test code', 'passcode': '456789'}, {}, '/v3/keyboardPwd/add', 'addType'),
    ('passcode_delete', {'card_id': 7}, {}, '/v3/keyboardPwd/delete', 'deleteType'),
    ('passcode_period', {'card_id': 7, 'start': 1000, 'end': 2000}, {}, '/v3/keyboardPwd/change', 'changeType'),
    ('lock_reset', {}, {}, '/v3/lock/delete', None),
    ('lock_init', {'name': 'New lock', 'lock_mac': 'AA:BB:CC:DD:EE:FF'}, {'lock_data': 'private-sdk-lock-data'}, '/v3/lock/initialize', None),
])
def test_cloud_sync_requires_sdk_success_and_never_replays_completed_work(client, owner, mobile_cloud, action, extra, result, expected, type_key):
    connect(client, owner)
    request_id = 'a'*32
    body = {'request_id': request_id, 'action': action, **extra}
    if action != 'lock_init': body['lock_id'] = 42
    prepared = client.post(PATH + '/mobile/prepare', headers=owner, json=body)
    assert prepared.status_code == 200, prepared.text
    assert not [p for p, b in mobile_cloud if p == expected]
    assert client.post(PATH + '/mobile/prepare', headers=owner, json=body).status_code == 409
    assert client.post(PATH + f'/mobile/{request_id}/sync', headers=owner).status_code == 409
    assert client.post(PATH + f'/mobile/{request_id}/complete', headers=owner, json={**result, 'sdk_success': False}).status_code == 422
    for _ in range(2):
        synced = client.post(PATH + f'/mobile/{request_id}/complete', headers=owner, json={**result, 'sdk_success': True})
        assert synced.json() == {'status': 'synced'}, synced.text
    writes = [b for p,b in mobile_cloud if p == expected]
    assert len(writes) == 1
    if type_key: assert writes[0][type_key] == 1  # Hardware already changed over Bluetooth.
    with SessionLocal() as db:
        row = db.query(TTLockMobileOperation).one()
        assert row.status == 'synced'
        assert 'private-' not in row.encrypted_payload + row.encrypted_result
    assert client.get(PATH + '/mobile/pending', headers=owner).json()['items'] == []


def test_failed_sync_is_recoverable_without_repeating_bluetooth(client, owner, mobile_cloud, monkeypatch):
    connect(client, owner)
    rid = 'b'*32
    client.post(PATH+'/mobile/prepare', headers=owner, json={'request_id': rid, 'action': 'card_add', 'lock_id': 42, 'name': 'Access'})
    real = t.request
    attempts = []
    def failing(region, path, body):
        if path == '/v3/identityCard/add':
            attempts.append(body)
            if len(attempts) == 1: raise HTTPException(502, 'Timeout')
        return real(region, path, body)
    monkeypatch.setattr(t, 'request', failing)
    result = client.post(PATH+f'/mobile/{rid}/complete', headers=owner, json={'sdk_success': True, 'card_number': '12345'})
    assert result.json()['status'] == 'sync_pending'
    pending = client.get(PATH+'/mobile/pending', headers=owner)
    assert '12345' not in pending.text and 'lock_data' not in pending.text
    assert pending.json()['items'][0]['status'] == 'sync_pending'
    _, other = user(client, owner, 'owner', 'mobile-other')
    assert client.post(PATH+f'/mobile/{rid}/sync', headers=other).status_code == 404
    assert client.post(PATH+f'/mobile/{rid}/sync', headers=owner).json()['status'] == 'synced'
    assert all(b['addType'] == 1 for b in attempts)
    assert client.post(PATH+f'/mobile/{rid}/complete', headers=owner, json={'sdk_success': True, 'card_number': '999'}).status_code == 409


def test_card_id_and_period_validation_before_bluetooth(client, owner, mobile_cloud):
    connect(client, owner)
    for body in [
        {'action': 'card_add', 'name': '   '},
        {'action': 'card_add', 'name': 'Test', 'start': 100, 'end': 0},
        {'action': 'card_period', 'card_id': 7, 'start': 200, 'end': 100},
        {'action': 'card_period', 'card_id': 7, 'start': 0, 'end': 0},
        {'action': 'card_delete'},
    ]:
        assert client.post(PATH+'/mobile/prepare', headers=owner, json={'request_id': 'c'*32, 'lock_id': 42, **body}).status_code == 422
    assert client.post(PATH+'/mobile/prepare', headers=owner, json={'request_id': 'c'*32, 'lock_id': 42, 'action': 'card_delete', 'card_id': 999}).status_code == 404


def test_ambiguous_cloud_success_is_reconciled_without_duplicate_registration(client, owner, mobile_cloud, monkeypatch):
    connect(client, owner)
    rid = 'd'*32
    client.post(PATH+'/mobile/prepare', headers=owner, json={'request_id': rid, 'action': 'card_add', 'lock_id': 42, 'name': 'Office card'})
    real = t.request
    writes = []
    def lost_response(region, path, body):
        if path == '/v3/identityCard/add':
            writes.append(body)
            raise HTTPException(502, 'Response lost after cloud commit')
        return real(region, path, body)
    monkeypatch.setattr(t, 'request', lost_response)
    assert client.post(PATH+f'/mobile/{rid}/complete', headers=owner, json={'sdk_success': True, 'card_number': '12345'}).json()['status'] == 'sync_pending'
    assert client.post(PATH+f'/mobile/{rid}/sync', headers=owner).json()['status'] == 'synced'
    assert len(writes) == 1


def test_pending_work_cannot_sync_to_a_different_ttlock_account(client, owner, mobile_cloud):
    connect(client, owner)
    rid = 'e'*32
    assert client.post(PATH+'/mobile/prepare', headers=owner, json={'request_id': rid, 'action': 'card_delete', 'lock_id': 42, 'card_id': 7}).status_code == 200
    assert client.put(PATH, headers=owner, json={**CONFIG, 'username': 'different-account'}).status_code == 200
    result = client.post(PATH+f'/mobile/{rid}/complete', headers=owner, json={'sdk_success': True})
    assert result.status_code == 409
    assert not [p for p, _ in mobile_cloud if p == '/v3/identityCard/delete']


@pytest.mark.parametrize('kind', ['card', 'passcode', 'fingerprint'])
def test_credential_lists_and_rename_verify_ownership(client, owner, mobile_cloud, kind):
    connect(client, owner)
    suffix = f'/locks/42/credentials/{kind}'
    listing = client.get(PATH+suffix, headers=owner)
    assert listing.status_code == 200
    assert listing.headers['cache-control'] == 'no-store'
    assert listing.json()['items'][0]['id'] == 7
    assert client.put(PATH+suffix+'/7/name', headers=owner, json={'name': 'New name'}).status_code == 200
    assert client.put(PATH+suffix+'/999/name', headers=owner, json={'name': 'New name'}).status_code == 404


def test_mobile_migration_matches_model(client, owner):
    import importlib.util
    from pathlib import Path
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import inspect
    from airlink.db import engine
    spec = importlib.util.spec_from_file_location('mobile_migration', Path(__file__).resolve().parents[1]/'database/versions/e31ab0472c58_ttlock_mobile.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with engine.begin() as db:
        module.op = Operations(MigrationContext.configure(db))
        module.downgrade()
        module.upgrade()
        assert {x['name'] for x in inspect(db).get_columns('ttlock_mobile_operations')} == {x.name for x in TTLockMobileOperation.__table__.columns}
