from datetime import timedelta
from types import SimpleNamespace as NS
import pytest
from fastapi import HTTPException
from sqlalchemy import select
from telethon import errors
from airlink import api, telegram_account as ta
from airlink.db import SessionLocal
from airlink.models import TelegramAccount, CustomerTelegramLink, now
from test_api import user

PATH = '/api/integrations/telegram-account'
LOGIN = {'api_id': 12345, 'api_hash': 'a' * 32, 'phone': '+9647501234567'}
PERSON = NS(id=998877, first_name='Example', last_name='Customer', username='example', bot=False, access_hash=987654321)


@pytest.fixture
def telegram(client, owner, monkeypatch):
    calls = []
    fake = NS(failure=None, two_step=False, result=NS(peer=NS(user_id=PERSON.id), users=[PERSON]))
    class Client:
        session = NS(save=lambda: 'PRIVATE_SESSION')
        async def connect(self): calls.append('connect')
        async def disconnect(self): calls.append('disconnect')
        async def send_code_request(self, phone):
            calls.append(('code', phone))
            if fake.failure: raise fake.failure
            return NS(phone_code_hash='PRIVATE_CODE_HASH')
        async def sign_in(self, **kwargs):
            calls.append(('sign_in', kwargs))
            if fake.failure: raise fake.failure
            if fake.two_step and 'password' not in kwargs:
                raise errors.SessionPasswordNeededError(None)
            return PERSON
        async def log_out(self):
            calls.append('logout')
            if fake.failure: raise fake.failure
            return True
        async def __call__(self, request):
            if isinstance(request, ta.functions.messages.SendMessageRequest):
                calls.append(('send', request))
                if fake.failure: raise fake.failure
                return NS()
            if isinstance(request, ta.functions.auth.LogOutRequest):
                calls.append('logout')
                if fake.failure: raise fake.failure
                return NS()
            calls.append(('lookup', request.phone))
            if fake.failure: raise fake.failure
            return fake.result
    monkeypatch.setattr(ta, 'client_for', lambda state: Client())
    monkeypatch.setattr(ta.customers, 'record_for', lambda db, user, cid: {'phone': LOGIN['phone']})
    actor = client.get('/api/auth/me', headers=owner).json()['id']
    return actor, calls, fake


def connect(client, owner):
    response = client.post(PATH + '/login', headers=owner, json=LOGIN)
    assert response.status_code == 200, response.text
    response = client.post(PATH + '/verify', headers=owner, json={'code': '12345'})
    assert response.status_code == 200, response.text
    return response


def phone_test_token(client, owner):
    result = client.post(PATH + '/users/7/lookup', headers=owner)
    assert result.status_code == 200, result.text
    return result.json()['test_token']


def clear_rate():
    for key in api.cache.scan_iter('telegram-account:rate:*'):
        api.cache.delete(key)


def test_login_encrypts_secrets_and_forgets_code_phone_after_authorization(client, owner, telegram):
    actor, calls, _ = telegram
    response = connect(client, owner)
    assert response.json()['stage'] == 'connected'
    for secret in ['PRIVATE_SESSION', 'PRIVATE_CODE_HASH', LOGIN['api_hash'], LOGIN['phone'], '12345']:
        assert secret not in response.text
    with SessionLocal() as db:
        row = db.get(TelegramAccount, actor)
        assert 'PRIVATE_SESSION' not in row.encrypted_state
        state = ta.read(row)
        assert state['session'] == 'PRIVATE_SESSION'
        assert not {'code', 'password', 'phone', 'phone_code_hash', 'expires_at'} & state.keys()
    assert calls.count('connect') == calls.count('disconnect') == 2
    assert client.post(PATH + '/login', headers=owner, json=LOGIN).status_code == 409


def test_two_step_password_not_saved(client, owner, telegram):
    actor, _, fake = telegram
    fake.two_step = True
    assert connect(client, owner).json()['stage'] == 'password'
    clear_rate()
    response = client.post(PATH + '/verify', headers=owner, json={'password': 'PRIVATE_PASSWORD'})
    assert response.status_code == 200 and response.json()['stage'] == 'connected'
    with SessionLocal() as db:
        assert 'PRIVATE_PASSWORD' not in str(ta.read(db.get(TelegramAccount, actor)))


@pytest.mark.parametrize('role', ['manager', 'technician', 'viewer'])
def test_nonowners_never_access_sessions_or_lookup(client, owner, telegram, role):
    _, headers = user(client, owner, role)
    for method, suffix, body in [('get', '', None), ('delete', '', None),
            ('post', '/login', LOGIN), ('post', '/verify', {'code': '12345'}), ('post', '/users/7/lookup', None)]:
        response = client.request(method, PATH + suffix, headers=headers, **({'json': body} if body else {}))
        assert response.status_code == 403
    assert telegram[1] == []


def test_lookup_uses_saved_phone_returns_only_basic_profile_never_links_bot(client, owner, telegram):
    connect(client, owner)
    response = client.post(PATH + '/users/7/lookup', headers=owner)
    assert response.status_code == 200, response.text
    assert response.json()['status'] == 'found'
    assert response.json()['profile'] == {'id': str(PERSON.id), 'first_name': 'Example', 'last_name': 'Customer', 'username': 'example'}
    assert response.json()['bot_link_required']
    assert ('lookup', LOGIN['phone']) in telegram[1]
    assert LOGIN['phone'] not in response.text
    with SessionLocal() as db:
        assert db.scalar(select(CustomerTelegramLink)) is None
    assert client.post(PATH + '/users/7/lookup', headers=owner).status_code == 429


@pytest.mark.parametrize('mode', ['empty', 'unoccupied', 'deleted', 'wrong_peer'])
def test_inaccessible_matches_are_unknown(client, owner, telegram, mode):
    connect(client, owner)
    fake = telegram[2]
    if mode == 'empty': fake.result = NS(users=[])
    if mode == 'unoccupied': fake.failure = errors.PhoneNotOccupiedError(None)
    if mode == 'deleted': fake.result = NS(peer=NS(user_id=9), users=[NS(id=9, deleted=True)])
    if mode == 'wrong_peer': fake.result = NS(peer=NS(user_id=9), users=[PERSON])
    response = client.post(PATH + '/users/7/lookup', headers=owner)
    assert response.status_code == 200, response.text
    assert response.json()['status'] == 'unknown' and response.json()['profile'] is None


def test_sas4_access_is_required_before_lookup(client, owner, telegram, monkeypatch):
    connect(client, owner)
    def denied(*args): raise HTTPException(403, 'No customer access')
    monkeypatch.setattr(ta.customers, 'record_for', denied)
    assert client.post(PATH + '/users/7/lookup', headers=owner).status_code == 403
    assert not [c for c in telegram[1] if isinstance(c, tuple) and c[0] == 'lookup']


def test_expired_login_and_invalid_validation_redact_inputs(client, owner, telegram):
    actor, _, _ = telegram
    assert client.post(PATH + '/login', headers=owner, json=LOGIN).status_code == 200
    with SessionLocal() as db:
        row = db.get(TelegramAccount, actor)
        state = ta.read(row)
        state['expires_at'] = (now() - timedelta(seconds=1)).isoformat()
        ta.save(db, row, state)
    assert client.get(PATH, headers=owner).json()['stage'] == 'disconnected'
    assert client.post(PATH + '/verify', headers=owner, json={'code': '12345'}).status_code == 409
    response = client.post(PATH + '/login', headers=owner, json={**LOGIN, 'api_hash': 'PRIVATE_BAD_HASH'})
    assert response.status_code == 422 and 'PRIVATE_BAD_HASH' not in response.text
    response = client.post(PATH + '/verify', headers=owner, json={'password': 'PRIVATE_PASSWORD' * 50})
    assert response.status_code == 422 and 'PRIVATE_PASSWORD' not in response.text


def test_flood_cooldown_survives_new_login_attempt(client, owner, telegram):
    actor, calls, fake = telegram
    fake.failure = errors.FloodWaitError(None, capture=120)
    response = client.post(PATH + '/login', headers=owner, json=LOGIN)
    assert response.status_code == 429 and response.headers['Retry-After'] == '120'
    assert client.delete(PATH, headers=owner).status_code == 429
    clear_rate()
    count = len(calls)
    assert client.post(PATH + '/login', headers=owner, json=LOGIN).status_code == 429
    assert len(calls) == count
    with SessionLocal() as db:
        assert db.get(TelegramAccount, actor).retry_at


def test_invalid_code_can_retry_but_errors_are_redacted(client, owner, telegram):
    _, _, fake = telegram
    client.post(PATH + '/login', headers=owner, json=LOGIN)
    fake.failure = errors.PhoneCodeInvalidError(None)
    assert client.post(PATH + '/verify', headers=owner, json={'code': '12345'}).status_code == 400
    assert client.get(PATH, headers=owner).json()['stage'] == 'code'
    clear_rate()
    fake.failure = RuntimeError('PRIVATE_SESSION PRIVATE_CODE_HASH')
    response = client.post(PATH + '/verify', headers=owner, json={'code': '12345'})
    assert response.status_code == 502 and 'PRIVATE' not in response.text


def test_disconnect_revokes_remote_session_before_deleting_local_copy(client, owner, telegram):
    actor, calls, fake = telegram
    connect(client, owner)
    fake.failure = OSError('network down')
    assert client.delete(PATH, headers=owner).status_code == 502
    assert client.get(PATH, headers=owner).json()['stage'] == 'connected'
    fake.failure = None
    assert client.delete(PATH, headers=owner).status_code == 200
    assert 'logout' in calls
    with SessionLocal() as db:
        assert db.get(TelegramAccount, actor) is None


def test_revoked_session_requires_reconnection(client, owner, telegram):
    connect(client, owner)
    telegram[2].failure = errors.SessionRevokedError(None)
    assert client.post(PATH + '/users/7/lookup', headers=owner).status_code == 409
    assert client.get(PATH, headers=owner).json()['stage'] == 'disconnected'


def test_other_owner_has_no_access_to_this_session(client, owner, telegram):
    connect(client, owner)
    _, other = user(client, owner, 'owner', name='secondowner')
    assert client.get(PATH, headers=other).json()['stage'] == 'disconnected'
    assert client.post(PATH + '/users/7/lookup', headers=other).status_code == 409
    assert client.delete(PATH, headers=other).status_code == 200
    assert client.get(PATH, headers=owner).json()['stage'] == 'connected'


def test_busy_lock_rejects_concurrent_actions(client, owner, telegram):
    actor = telegram[0]
    with ta.locked(actor):
        assert client.post(PATH + '/login', headers=owner, json=LOGIN).status_code == 409
    assert not api.cache.exists('telegram-account:lock:' + actor)


def test_redis_outage_fails_closed_before_connecting(client, owner, telegram, monkeypatch):
    from redis.exceptions import ConnectionError
    def unavailable(*args, **kwargs): raise ConnectionError('PRIVATE_REDIS_URI')
    monkeypatch.setattr(api.cache, 'set', unavailable)
    response = client.post(PATH + '/login', headers=owner, json=LOGIN)
    assert response.status_code == 503 and 'PRIVATE' not in response.text
    assert telegram[1] == []


def test_same_telegram_identity_shares_lookup_cooldown_between_owners(client, owner, telegram):
    connect(client, owner)
    _, other = user(client, owner, 'owner', name='secondowner')
    connect(client, other)
    assert client.post(PATH + '/users/7/lookup', headers=owner).status_code == 200
    assert client.post(PATH + '/users/7/lookup', headers=other).status_code == 429


def test_lookup_flood_blocks_same_identity_on_another_owner(client, owner, telegram):
    connect(client, owner)
    _, other = user(client, owner, 'owner', name='secondowner')
    connect(client, other)
    telegram[2].failure = errors.FloodWaitError(None, capture=120)
    assert client.post(PATH + '/users/7/lookup', headers=owner).status_code == 429
    telegram[2].failure = None
    response = client.post(PATH + '/users/7/lookup', headers=other)
    assert response.status_code == 429 and int(response.headers['Retry-After']) > 100


def test_real_client_uses_memory_session_without_lookup_retries(monkeypatch):
    import asyncio
    from telethon.sessions import StringSession
    options = {}
    def constructor(session, api_id, api_hash, **kwargs):
        assert isinstance(session, StringSession)
        options.update(kwargs)
        return NS(session=session)
    monkeypatch.setattr(ta, 'TelegramClient', constructor)
    async def check():
        result = ta.client_for({'api_id': 123, 'api_hash': 'a' * 32, 'stage': 'connected'})
        assert result.session.save_entities is False
    asyncio.run(check())
    assert options['request_retries'] == 0
    assert options['flood_sleep_threshold'] == 0 and options['receive_updates'] is False


@pytest.mark.parametrize('language', ['en', 'ku', 'ar'])
def test_phone_test_sends_once_to_matched_peer_from_connected_account(client, owner, telegram, language):
    connect(client, owner)
    token = phone_test_token(client, owner)
    response = client.post(PATH + '/users/7/test', headers=owner, json={'test_token': token, 'language': language})
    assert response.status_code == 200, response.text
    assert response.json()['sent'] and response.json()['sender'] == 'telegram_account'
    sent = [c[1] for c in telegram[1] if isinstance(c, tuple) and c[0] == 'send']
    assert len(sent) == 1 and sent[0].peer.user_id == PERSON.id
    assert sent[0].peer.access_hash == PERSON.access_hash
    assert sent[0].message == ta.TEST_MESSAGES[language]
    assert sent[0].allow_paid_stars is None
    clear_rate()
    assert client.post(PATH + '/users/7/test', headers=owner, json={'test_token': token}).status_code == 409
    assert len([c for c in telegram[1] if isinstance(c, tuple) and c[0] == 'send']) == 1
    with SessionLocal() as db:
        assert db.scalar(select(CustomerTelegramLink)) is None


@pytest.mark.parametrize('change', ['phone', 'username', 'sender', 'customer', 'expired', 'tampered'])
def test_phone_test_rejects_stale_or_modified_recipient(client, owner, telegram, monkeypatch, change):
    import time
    connect(client, owner)
    token = phone_test_token(client, owner)
    path = PATH + '/users/7/test'
    if change == 'phone':
        monkeypatch.setattr(ta.customers, 'record_for', lambda *args: {'phone': '+9647501234599'})
    if change == 'username':
        monkeypatch.setattr(ta.customers, 'record_for', lambda *args: {'phone': LOGIN['phone'], 'username': 'reassigned'})
    if change == 'sender':
        with SessionLocal() as db:
            row = db.get(TelegramAccount, telegram[0])
            state = ta.read(row)
            state['profile']['id'] = '999'
            ta.save(db, row, state)
    if change == 'customer': path = PATH + '/users/8/test'
    if change == 'expired': token = ta.cipher().encrypt_at_time(ta.cipher().decrypt(token.encode()), int(time.time()) - 301).decode()
    if change == 'tampered': token = 'not-a-valid-token'
    assert client.post(path, headers=owner, json={'test_token': token}).status_code == 409
    assert not [c for c in telegram[1] if isinstance(c, tuple) and c[0] == 'send']


@pytest.mark.parametrize('error,status', [(errors.UserPrivacyRestrictedError(None),403),
    (errors.PeerFloodError(None),429), (OSError('PRIVATE_SESSION'),502)])
def test_phone_test_handles_rejection_and_ambiguous_failure_without_retry(client, owner, telegram, error, status):
    connect(client, owner)
    token = phone_test_token(client, owner)
    telegram[2].failure = error
    result = client.post(PATH + '/users/7/test', headers=owner, json={'test_token': token})
    assert result.status_code == status and 'PRIVATE_SESSION' not in result.text
    clear_rate()
    telegram[2].failure = None
    assert client.post(PATH + '/users/7/test', headers=owner, json={'test_token': token}).status_code == 409
    assert len([c for c in telegram[1] if isinstance(c, tuple) and c[0] == 'send']) == 1


def test_phone_test_denies_managers_and_other_owners(client, owner, telegram):
    connect(client, owner)
    token = phone_test_token(client, owner)
    _, manager = user(client, owner, 'manager')
    assert client.post(PATH + '/users/7/test', headers=manager, json={'test_token': token}).status_code == 403
    _, other = user(client, owner, 'owner', name='secondowner')
    connect(client, other)
    assert client.post(PATH + '/users/7/test', headers=other, json={'test_token': token}).status_code == 409
    assert not [c for c in telegram[1] if isinstance(c, tuple) and c[0] == 'send']


def test_phone_test_new_lookup_cannot_bypass_recipient_cooldown(client, owner, telegram):
    connect(client, owner)
    token = phone_test_token(client, owner)
    assert client.post(PATH + '/users/7/test', headers=owner, json={'test_token': token}).status_code == 200
    api.cache.delete('telegram-account:rate:lookup:' + str(PERSON.id))
    token = phone_test_token(client, owner)
    assert client.post(PATH + '/users/7/test', headers=owner, json={'test_token': token}).status_code == 429


def test_unknown_phone_never_gets_send_token(client, owner, telegram):
    connect(client, owner)
    telegram[2].result = NS(users=[])
    assert phone_test_token(client, owner) is None
