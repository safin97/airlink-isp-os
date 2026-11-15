"""Owner-only Telegram phone lookup and explicit customer test messages."""
import asyncio
import hashlib
import json
import re
import secrets
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Literal, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from redis.exceptions import RedisError, WatchError
from telethon import TelegramClient, errors, functions, types
from telethon.sessions import StringSession
from . import customer_telegram as customers
from .db import get_db
from .models import TelegramAccount, now, uid, audit
from .security import current_user, cipher, aware

router = APIRouter(prefix='/api/integrations/telegram-account', tags=['Telegram account'])


def owner(user=Depends(current_user)):
    if not user.active or user.role != 'owner':
        raise HTTPException(403, 'Only an owner can use Telegram account lookup.')
    return user


class LoginInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    api_id: int = Field(gt=0, le=2147483647)
    api_hash: SecretStr = Field(min_length=32, max_length=32)
    phone: str = Field(min_length=8, max_length=64)


class VerifyInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    code: Optional[SecretStr] = Field(default=None, min_length=1, max_length=16)
    password: Optional[SecretStr] = Field(default=None, min_length=1, max_length=256)


class PhoneTestInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    test_token: SecretStr = Field(min_length=1, max_length=4096)
    language: Literal['en', 'ku', 'ar'] = 'en'


TEST_MESSAGES = {
    'en': 'AirLink: This is a test message from your internet service provider.',
    'ku': 'AirLink: ئەڤە پەیامەکا تاقیکرنێ یە ژ دابینکەرێ ئینتەرنێتا تە.',
    'ar': 'AirLink: هذه رسالة تجريبية من مزود خدمة الإنترنت لديك.',
}


def read(row):
    return json.loads(cipher().decrypt(row.encrypted_state.encode())) if row else {}


def save(db, row, state):
    row.encrypted_state = cipher().encrypt(json.dumps(state).encode()).decode()
    db.add(row)
    db.commit()


def public(state):
    expired = state.get('expires_at') and datetime.fromisoformat(state['expires_at']) <= now()
    return {'stage': 'disconnected' if expired else state.get('stage', 'disconnected'),
            'profile': state.get('profile') if state.get('stage') == 'connected' else None}


def profile(person):
    return {'id': str(person.id), 'first_name': person.first_name or '',
            'last_name': person.last_name or '', 'username': person.username or None}


@contextmanager
def locked(user_id):
    # Serialize login/lookup/logout across processes; fail closed if Redis is down.
    from .api import cache
    key, token = 'telegram-account:lock:' + user_id, uid()
    try:
        acquired = cache.set(key, token, nx=True, ex=90)
    except RedisError:
        raise HTTPException(503, 'Telegram account service is temporarily unavailable.') from None
    if not acquired:
        raise HTTPException(409, 'Another Telegram account request is running. Try again shortly.')
    try:
        yield
    finally:
        try:
            with cache.pipeline() as pipe:
                pipe.watch(key)
                if pipe.get(key) == token:
                    pipe.multi()
                    pipe.delete(key)
                    pipe.execute()
        except (RedisError, WatchError):
            pass  # TTL still releases the lock; never mask the operation result.


def throttle(key, seconds):
    from .api import cache
    try:
        if not cache.set('telegram-account:rate:' + key, '1', nx=True, ex=seconds):
            raise HTTPException(429, 'Please wait before trying Telegram again.', headers={'Retry-After': str(max(1, cache.ttl('telegram-account:rate:' + key)))})
    except RedisError:
        raise HTTPException(503, 'Telegram account service is temporarily unavailable.') from None


def client_for(state):
    client = TelegramClient(StringSession(state.get('session', '')), state['api_id'], state['api_hash'],
        # Disable automatic retries for lookup; Telethon's server-error retry can
        # otherwise repeat resolvePhone inside Telegram's three-second limit.
        receive_updates=False, timeout=8,
        request_retries=0 if state.get('stage') == 'connected' else 1, connection_retries=0,
        auto_reconnect=False, flood_sleep_threshold=0, raise_last_call_error=True,
        device_model='AirLink ISP OS', system_version='AirLink', app_version='1.0')
    client.session.save_entities = False
    return client


def check_cooldown(row):
    if row.retry_at and aware(row.retry_at) > now():
        wait = max(1, int((aware(row.retry_at) - now()).total_seconds()) + 1)
        raise HTTPException(429, 'Telegram requested a cooldown. Try again later.', headers={'Retry-After': str(wait)})


def perform(db, row, state, operation, delivery=False):
    check_cooldown(row)

    async def run():
        client = client_for(state)
        try:
            await client.connect()
            return await operation(client)
        finally:
            await client.disconnect()

    try:
        return asyncio.run(asyncio.wait_for(run(), timeout=45))
    except HTTPException:
        raise
    except (errors.FloodWaitError, errors.FloodPremiumWaitError, errors.FloodTestPhoneWaitError) as exc:
        wait = max(3, exc.seconds)
        row.retry_at = now() + timedelta(seconds=wait)
        # Keep the cooldown even if the initial code request failed.
        save(db, row, state)
        if state.get('profile'):
            from .api import cache
            try:
                cache.set('telegram-account:rate:lookup:' + state['profile']['id'], '1', ex=wait)
            except RedisError:
                pass  # The persistent owner cooldown still applies.
        raise HTTPException(429, 'Telegram requested a cooldown. Try again later.', headers={'Retry-After': str(wait)}) from None
    except (errors.PhoneCodeInvalidError, errors.PasswordHashInvalidError):
        raise HTTPException(400, 'Incorrect Telegram code or two-step password.') from None
    except errors.PhoneCodeExpiredError:
        state['expires_at'] = now().isoformat()
        save(db, row, state)
        raise HTTPException(409, 'Telegram code expired. Cancel and request a new code.') from None
    except (errors.AuthKeyUnregisteredError, errors.SessionRevokedError, errors.UserDeactivatedError):
        if db.get(TelegramAccount, row.user_id):
            db.delete(row)
            db.commit()
        raise HTTPException(409, 'Telegram session is no longer valid. Sign in again.') from None
    except (errors.ApiIdInvalidError, errors.PhoneNumberInvalidError, errors.PhoneNumberBannedError):
        raise HTTPException(400, 'Telegram rejected these application credentials or phone number.') from None
    except Exception:
        # Never return/log exception text: it may contain credentials or phone numbers.
        if delivery:
            raise HTTPException(502, 'Telegram did not confirm the test. Check the customer chat before trying again; the message may have been sent.') from None
        raise HTTPException(502, 'Telegram could not complete the request. Check connectivity and try again.') from None


@router.get('')
def status(user=Depends(owner), db=Depends(get_db)):
    row = db.get(TelegramAccount, user.id)
    return public(read(row))


@router.post('/login')
def login(data: LoginInput, user=Depends(owner), db=Depends(get_db)):
    phone = customers.normalized_phone(data.phone)
    api_hash = data.api_hash.get_secret_value()
    if not phone or not re.fullmatch('[0-9a-fA-F]{32}', api_hash):
        raise HTTPException(422, 'Enter a valid phone number, API ID and API hash from my.telegram.org.')
    with locked(user.id):
        row = db.get(TelegramAccount, user.id)
        if read(row).get('stage') == 'connected':
            raise HTTPException(409, 'Disconnect the current Telegram account first.')
        throttle('login:' + user.id, 60)
        row = row or TelegramAccount(user_id=user.id)
        state = {'api_id': data.api_id, 'api_hash': api_hash, 'phone': '+' + phone,
                 'stage': 'disconnected', 'expires_at': (now() + timedelta(minutes=10)).isoformat()}

        async def request(client):
            sent = await client.send_code_request(state['phone'])
            if not getattr(sent, 'phone_code_hash', None):
                raise HTTPException(409, 'Telegram requires a different login method. Use your Telegram app and try again later.')
            state.update(stage='code', phone_code_hash=sent.phone_code_hash, session=client.session.save())
            save(db, row, state)
            audit(db, user, 'telegram_account.code_requested')
            db.commit()
            return public(state)
        return perform(db, row, state, request)


@router.post('/verify')
def verify(data: VerifyInput, user=Depends(owner), db=Depends(get_db)):
    with locked(user.id):
        row = db.get(TelegramAccount, user.id)
        state = read(row)
        if public(state)['stage'] not in ('code', 'password'):
            raise HTTPException(409, 'Request a new Telegram login code first.')
        throttle('verify:' + user.id, 3)

        async def request(client):
            try:
                if state['stage'] == 'password':
                    if not data.password:
                        raise HTTPException(422, 'Enter your Telegram two-step password.')
                    person = await client.sign_in(password=data.password.get_secret_value())
                else:
                    code = data.code.get_secret_value().strip() if data.code else ''
                    if not re.fullmatch('[0-9]{4,8}', code):
                        raise HTTPException(422, 'Enter the numeric login code from Telegram.')
                    person = await client.sign_in(phone=state['phone'], code=code, phone_code_hash=state['phone_code_hash'])
            except errors.SessionPasswordNeededError:
                state.update(stage='password', session=client.session.save())
                save(db, row, state)
                return public(state)
            if not person or getattr(person, 'bot', False):
                raise HTTPException(400, 'A Telegram user account is required.')
            clean = {key: state[key] for key in ('api_id', 'api_hash')}
            clean.update(stage='connected', session=client.session.save(), profile=profile(person))
            save(db, row, clean)
            audit(db, user, 'telegram_account.connected')
            db.commit()
            return public(clean)
        return perform(db, row, state, request)


@router.delete('')
def disconnect(user=Depends(owner), db=Depends(get_db)):
    with locked(user.id):
        row = db.get(TelegramAccount, user.id)
        if not row:
            return {'stage': 'disconnected', 'profile': None}
        # Cancelling a failed login must not erase Telegram's flood cooldown.
        check_cooldown(row)
        state = read(row)
        if state.get('session'):
            async def request(client):
                # Use the RPC directly: Telethon.log_out() hides revoked-session
                # errors, preventing us from removing an already-invalid key.
                await client(functions.auth.LogOutRequest())
            perform(db, row, state, request)
        db.delete(row)
        audit(db, user, 'telegram_account.disconnected')
        db.commit()
        return {'stage': 'disconnected', 'profile': None}


@router.post('/users/{customer_id}/lookup')
def lookup(customer_id: int, user=Depends(owner), db=Depends(get_db)):
    # Accept only a customer ID, never arbitrary phone input. Enforce SAS4 access.
    record = customers.record_for(db, user, customer_id)
    phone = customers.normalized_phone(record.get('phone'))
    if not phone:
        raise HTTPException(422, 'Save a valid customer phone number in ISP card first.')
    with locked(user.id):
        row = db.get(TelegramAccount, user.id)
        state = read(row)
        if public(state)['stage'] != 'connected':
            raise HTTPException(409, 'Connect your Telegram account in My account → Telegram account lookup first.')
        async def request(client):
            # Limit at the actual RPC, after connecting, so variable connection
            # times cannot squeeze two owners' requests inside three seconds.
            throttle('lookup:' + state['profile']['id'], 3)
            try:
                result = await client(functions.contacts.ResolvePhoneRequest(phone='+' + phone))
            except (errors.PhoneNotOccupiedError, errors.PhoneNumberUnoccupiedError):
                result = None
            peer_id = getattr(getattr(result, 'peer', None), 'user_id', None)
            person = next((p for p in getattr(result, 'users', []) if p.id == peer_id
                           and not getattr(p, 'deleted', False) and not getattr(p, 'bot', False)), None)
            # A lookup is not consent to receive bot messages. Never modify bot links.
            test_token = None
            if person and getattr(person, 'access_hash', None) is not None and not getattr(person, 'min', False):
                # Short-lived, encrypted recipient details bind a button click to
                # the displayed match, saved customer phone and connected sender.
                target = {'purpose': 'customer_phone_test', 'owner': user.id, 'customer': customer_id, 'username': record.get('username'),
                          'phone_hash': customers.phone_hash(record), 'sender': state['profile']['id'],
                          'peer': person.id, 'access_hash': person.access_hash, 'random_id': secrets.randbits(63)}
                test_token = cipher().encrypt(json.dumps(target).encode()).decode()
            return {'status': 'found' if person else 'unknown', 'profile': profile(person) if person else None,
                    'checked_at': now().isoformat(), 'bot_link_required': True, 'test_token': test_token}
        return perform(db, row, state, request)


@router.post('/users/{customer_id}/test')
def send_phone_test(customer_id: int, data: PhoneTestInput, user=Depends(owner), db=Depends(get_db)):
    record = customers.record_for(db, user, customer_id)
    token = data.test_token.get_secret_value()
    try:
        target = json.loads(cipher().decrypt(token.encode(), ttl=300))
        if not isinstance(target, dict) or target.get('purpose') != 'customer_phone_test':
            raise ValueError()
    except Exception:
        raise HTTPException(409, 'Phone lookup expired. Check the saved phone again before sending a test.') from None
    with locked(user.id):
        row = db.get(TelegramAccount, user.id)
        state = read(row)
        if public(state)['stage'] != 'connected':
            raise HTTPException(409, 'Connect your Telegram account before sending a phone test.')
        if (target.get('owner') != user.id or target.get('customer') != customer_id
                or target.get('sender') != state['profile']['id']
                or target.get('username') != record.get('username')
                or not customers.phone_hash(record) or target.get('phone_hash') != customers.phone_hash(record)):
            raise HTTPException(409, 'The customer phone or Telegram account changed. Check the saved phone again.')

        async def request(client):
            from .api import cache
            from .recharge_telegram import language_for, test_message
            throttle('test:' + state['profile']['id'] + ':' + str(target['peer']), 30)
            try:
                # Consume before sending, including ambiguous failures. No queue,
                # background retry, or repeat send from the same lookup token.
                if not cache.set('telegram-account:test-used:' + hashlib.sha256(token.encode()).hexdigest(),
                                 '1', nx=True, ex=600):
                    raise HTTPException(409, 'This test was already attempted. Check the chat, then check the saved phone again for a new test.')
            except RedisError:
                raise HTTPException(503, 'Test delivery protection is unavailable. Try again later.') from None
            audit(db, user, 'telegram_account.test.attempt', str(customer_id))
            db.commit()
            try:
                await client(functions.messages.SendMessageRequest(
                    peer=types.InputPeerUser(target['peer'], target['access_hash']),
                    message=test_message(db, record, language_for(db, data.language)), random_id=target['random_id'], no_webpage=True))
            except (errors.UserPrivacyRestrictedError, errors.UserIsBlockedError, errors.YouBlockedUserError,
                    errors.ChatWriteForbiddenError, errors.UserNotMutualContactError):
                raise HTTPException(403, 'Telegram privacy or blocking settings prevent this account from messaging the customer.') from None
            except errors.PeerFloodError:
                raise HTTPException(429, 'Telegram restricted messaging from this account. Check the account in Telegram before trying again.') from None
            audit(db, user, 'telegram_account.test.accepted', str(customer_id))
            db.commit()
            return {'sent': True, 'sent_at': now().isoformat(), 'sender': 'telegram_account'}

        return perform(db, row, state, request, delivery=True)
