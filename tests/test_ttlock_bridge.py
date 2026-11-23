from datetime import timedelta
import pytest
from airlink import ttlock as t
from airlink.db import SessionLocal
from airlink.models import TTLockBridge, TTLockBridgeJob, now
from test_ttlock_mobile import mobile_cloud, connect
from test_ttlock import cloud, CONFIG, PATH
from test_api import user

B = PATH + '/bridge'


def phone(client, owner):
    response = client.post(B+'/phones', headers=owner, json={'name': 'Office phone'})
    assert response.status_code == 200, response.text
    data = response.json()
    return data['id'], {**owner, 'X-AirLink-Bridge': data['token']}


def queue(client, owner, bridge_id, rid='a'*32, **params):
    return client.post(B+'/jobs', headers=owner, json={'request_id': rid, 'bridge_id': bridge_id,
        'parameters': {'action': 'battery', 'lock_id': 42, **params}})


def test_bridge_permissions_scope_and_no_credentials_in_browser(client, owner, mobile_cloud):
    connect(client, owner)
    bid, headers = phone(client, owner)
    listing = client.get(B+'/phones', headers=owner)
    assert listing.headers['cache-control'] == 'no-store'
    assert listing.json()['items'][0]['name'] == 'Office phone'
    assert 'token' not in listing.text and 'private-' not in listing.text
    _, other = user(client, owner, 'owner', 'bridge-other')
    _, manager = user(client, owner, 'manager', 'bridge-manager')
    for auth, code in (({}, 401), (manager, 403)):
        assert client.get(B+'/phones', headers=auth).status_code == code
        assert client.post(B+'/phones', headers=auth, json={'name': 'Phone'}).status_code == code
    assert client.post(B+f'/phones/{bid}/poll', headers={**other, 'X-AirLink-Bridge': headers['X-AirLink-Bridge']}).status_code == 404
    assert client.post(B+f'/phones/{bid}/poll', headers={**owner, 'X-AirLink-Bridge': '0'*64}).status_code == 403
    assert queue(client, owner, bid, lock_id=99).status_code == 404
    assert queue(client, owner, bid).status_code == 200
    assert client.get(B+'/jobs/'+'a'*32, headers=other).status_code == 404
    assert client.post(B+'/jobs/'+'a'*32+'/cancel', headers=other).status_code == 404


def test_claim_once_complete_idempotently_and_never_replay_hardware(client, owner, mobile_cloud):
    connect(client, owner)
    bid, headers = phone(client, owner)
    assert queue(client, owner, bid, action='unlock').status_code == 200
    assert queue(client, owner, bid, action='unlock').status_code == 409
    assert queue(client, owner, bid, rid='b'*32).status_code == 409
    pending = client.post(B+f'/phones/{bid}/poll', headers=headers).json()['job']
    assert pending['action'] == 'unlock' and pending['lock_name'] == 'Office door'
    assert client.post(B+'/jobs/'+'a'*32+'/claim', headers=owner).status_code == 422
    claim = client.post(B+'/jobs/'+'a'*32+'/claim', headers=headers)
    assert claim.status_code == 200, claim.text
    assert claim.json()['parameters']['action'] == 'unlock'
    assert client.post(B+'/jobs/'+'a'*32+'/claim', headers=headers).status_code == 409
    assert client.post(B+'/jobs/'+'a'*32+'/cancel', headers=owner).status_code == 409
    assert client.post(B+f'/phones/{bid}/poll', headers=headers).json()['job'] is None
    body = {'claim_token': claim.json()['claim_token'], 'status': 'succeeded', 'result': {'battery': 80}}
    for _ in range(2):
        assert client.post(B+'/jobs/'+'a'*32+'/complete', headers=owner, json=body).json()['status'] == 'succeeded'
    assert client.post(B+'/jobs/'+'a'*32+'/complete', headers=owner, json={**body, 'result': {'battery': 70}}).status_code == 409
    result = client.get(B+'/jobs/'+'a'*32, headers=owner).json()
    assert result['result']['data']['battery'] == 80
    assert queue(client, owner, bid, rid='b'*32).status_code == 200
    assert not [p for p, _ in mobile_cloud if p in ('/v3/lock/unlock', '/v3/lock/lock')]


def test_expiry_cancel_and_bridge_revocation(client, owner, mobile_cloud):
    connect(client, owner)
    bid, headers = phone(client, owner)
    queue(client, owner, bid)
    with SessionLocal() as db:
        db.get(TTLockBridgeJob, 'a'*32).expires_at = now() - timedelta(seconds=1)
        db.commit()
    assert client.get(B+'/jobs/'+'a'*32, headers=owner).json()['status'] == 'expired'
    assert client.post(B+'/jobs/'+'a'*32+'/claim', headers=headers).status_code == 409
    queue(client, owner, bid, rid='b'*32)
    assert client.post(B+'/jobs/'+'b'*32+'/cancel', headers=owner).status_code == 200
    assert client.post(B+'/jobs/'+'b'*32+'/claim', headers=headers).status_code == 409
    queue(client, owner, bid, rid='c'*32)
    assert client.delete(B+f'/phones/{bid}', headers=headers).status_code == 200
    assert client.get(B+'/jobs/'+'c'*32, headers=owner).json()['status'] == 'cancelled'
    assert client.get(B+'/phones', headers=owner).json()['items'] == []
    assert queue(client, owner, bid, rid='d'*32).status_code == 409
    assert client.post(B+f'/phones/{bid}/poll', headers=headers).status_code == 403


def test_running_timeout_unknown_and_late_result_allowed_without_reclaim(client, owner, mobile_cloud):
    connect(client, owner)
    bid, headers = phone(client, owner)
    queue(client, owner, bid)
    claim = client.post(B+'/jobs/'+'a'*32+'/claim', headers=headers).json()
    with SessionLocal() as db:
        db.get(TTLockBridgeJob, 'a'*32).expires_at = now() - timedelta(seconds=1)
        db.commit()
    assert client.get(B+'/jobs/'+'a'*32, headers=owner).json()['status'] == 'unknown'
    assert client.post(B+'/jobs/'+'a'*32+'/claim', headers=headers).status_code == 409
    assert client.post(B+'/jobs/'+'a'*32+'/complete', headers=owner,
        json={'claim_token': claim['claim_token'], 'status': 'succeeded', 'result': {'battery': 10}}).status_code == 200


def test_credentials_encrypted_only_delivered_to_claiming_phone(client, owner, mobile_cloud):
    connect(client, owner)
    bid, headers = phone(client, owner)
    assert queue(client, owner, bid, action='passcode_add', name='Guest', passcode='456789').status_code == 200
    polled = client.post(B+f'/phones/{bid}/poll', headers=headers)
    assert '456789' not in polled.text
    assert '456789' not in client.get(B+'/jobs/'+'a'*32, headers=owner).text
    with SessionLocal() as db:
        assert '456789' not in db.get(TTLockBridgeJob, 'a'*32).encrypted_payload
        assert headers['X-AirLink-Bridge'] not in db.get(TTLockBridge, bid).token_hash
    claimed = client.post(B+'/jobs/'+'a'*32+'/claim', headers=headers).json()
    assert claimed['parameters']['passcode'] == '456789'
    assert claimed['operation'] is True
    assert 'lock_data' not in claimed


def test_account_switch_blocks_queued_request(client, owner, mobile_cloud):
    connect(client, owner)
    bid, headers = phone(client, owner)
    queue(client, owner, bid)
    assert client.put(PATH, headers=owner, json={**CONFIG, 'username': 'switched'}).status_code == 200
    assert client.get(B+'/phones', headers=owner).json()['items'] == []
    assert client.post(B+'/jobs/'+'a'*32+'/claim', headers=headers).status_code == 409
    assert client.post(B+f'/phones/{bid}/poll', headers=headers).status_code == 409


@pytest.mark.parametrize('params', [
    {'action': 'lock_init', 'name': 'New', 'lock_mac': 'AA:BB:CC:DD:EE:FF'},
    {'action': 'battery', 'lock_data': 'injected'},
    {'action': 'passcode_add', 'name': 'Bad', 'passcode': 'abcd'},
    {'action': 'card_period', 'card_id': 7, 'start': 20, 'end': 10},
])
def test_invalid_actions_never_queue(client, owner, mobile_cloud, params):
    connect(client, owner)
    bid, _ = phone(client, owner)
    assert queue(client, owner, bid, **params).status_code == 422


def test_bridge_migration_matches_models(client, owner):
    import importlib.util
    from pathlib import Path
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import inspect
    from airlink.db import engine
    spec = importlib.util.spec_from_file_location('bridge_migration', Path(__file__).resolve().parents[1]/'database/versions/f42bc1583d69_ttlock_bridge.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with engine.begin() as db:
        module.op = Operations(MigrationContext.configure(db))
        module.downgrade()
        module.upgrade()
        for model in (TTLockBridge, TTLockBridgeJob):
            assert {c['name'] for c in inspect(db).get_columns(model.__tablename__)} == {c.name for c in model.__table__.columns}
