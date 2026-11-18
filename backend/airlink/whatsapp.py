"""Owner-selected WhatsApp Cloud API notifications; never performs a recharge."""
import asyncio
import hashlib
import json
import re
from contextlib import contextmanager
from datetime import timedelta, timezone
from zoneinfo import ZoneInfo

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select, delete
from . import customer_telegram as customers
from .db import get_db, SessionLocal
from .models import (WhatsAppSettings as Settings, WhatsAppCustomer as Customer,
                     WhatsAppEvent as Event, SAS4UserConnection, User, now, uid, audit)
from .security import owner, cipher, aware

router = APIRouter(prefix='/api/integrations/whatsapp', tags=['WhatsApp'])
KINDS = ('recharge', 'expiry_3days', 'expired')
METHODS = {'card', 'credit', 'extend', 'fib', 'fastpay'}
DEFAULTS = {'api_version': 'v27.0', 'phone_number_id': '', 'business_account_id': '',
            'language': 'en_US', 'timezone': 'Asia/Baghdad',
            **{kind: False for kind in KINDS},
            **{kind + '_template': 'airlink_' + kind for kind in KINDS}}


class SettingsInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    api_version: str = Field(default='v27.0', pattern=r'^v[0-9]{1,3}\.0$')
    phone_number_id: str = Field(pattern=r'^[0-9]{5,32}$')
    business_account_id: str = Field(pattern=r'^[0-9]{5,32}$')
    access_token: str = Field(default='', max_length=4096)
    language: str = Field(default='en_US', pattern=r'^[a-z]{2,3}(?:_[A-Z]{2})?$')
    timezone: str = Field(default='Asia/Baghdad', max_length=64)
    recharge: bool = False
    expiry_3days: bool = False
    expired: bool = False
    recharge_template: str = Field(default='airlink_recharge', pattern=r'^[a-z0-9_]{1,512}$')
    expiry_3days_template: str = Field(default='airlink_expiry_3days', pattern=r'^[a-z0-9_]{1,512}$')
    expired_template: str = Field(default='airlink_expired', pattern=r'^[a-z0-9_]{1,512}$')

    @field_validator('timezone')
    @classmethod
    def valid_zone(cls, value):
        try:
            ZoneInfo(value)
        except (ValueError, KeyError):
            raise ValueError('Invalid timezone') from None
        return value

    @field_validator('access_token')
    @classmethod
    def valid_token(cls, value):
        if value and (len(value) < 20 or not re.fullmatch(r'[A-Za-z0-9_.|\-]+', value)):
            raise ValueError('Invalid access token')
        return value


@contextmanager
def locked():
    from .api import cache
    from redis.exceptions import RedisError
    lock = cache.lock('whatsapp:operations', timeout=300, blocking=False)
    try:
        acquired = lock.acquire(blocking=False)
    except RedisError:
        raise HTTPException(503, 'WhatsApp operation protection is unavailable.') from None
    if not acquired:
        raise HTTPException(409, 'WhatsApp is busy. Try again shortly.')
    try:
        yield
    finally:
        if lock.owned():
            lock.release()


def configured(db):
    row = db.get(Settings, 1)
    user = db.get(User, row.user_id) if row else None
    connection = db.get(SAS4UserConnection, row.user_id) if row else None
    return row if (user and user.active and user.role == 'owner' and connection
                   and connection.username == row.sas4_username) else None


def event_public(event):
    return {key: getattr(event, key) for key in ('kind', 'status', 'detail', 'created_at', 'accepted_at')}


@router.get('')
def status(user=Depends(owner), db=Depends(get_db)):
    row = db.get(Settings, 1)
    return {**(row.config if row else DEFAULTS), 'token_saved': bool(row),
            'selected_owner': bool(row and row.user_id == user.id),
            'account_ready': bool(configured(db)),
            'verified_at': row.verified_at if row else None,
            'retry_at': row.retry_at if row else None,
            'last_error': row.last_error if row else None,
            'events': [event_public(e) for e in db.scalars(select(Event).order_by(Event.created_at.desc()).limit(20))]}


@router.put('')
def configure(data: SettingsInput, user=Depends(owner), db=Depends(get_db)):
    with locked():
        row = db.get(Settings, 1)
        connection = db.get(SAS4UserConnection, user.id)
        if not connection:
            raise HTTPException(409, 'Connect your owner SAS4 account first.')
        if not data.access_token and (not row or row.user_id != user.id):
            raise HTTPException(422, 'Enter the WhatsApp system user access token.')
        config = data.model_dump(exclude={'access_token'})
        same = bool(row and row.user_id == user.id and row.sas4_username == connection.username
                    and not data.access_token and all(row.config.get(k) == v for k, v in config.items() if k not in KINDS))
        if any(config[k] for k in KINDS) and not (same and row.verified_at):
            raise HTTPException(409, 'Save with notifications off, then check the connection and templates before enabling notifications.')
        if row is None:
            row = Settings(id=1)
            db.add(row)
        if not same:
            row.verified_at = None
            row.version = uid()
        row.user_id, row.sas4_username = user.id, connection.username
        row.config = config
        if data.access_token:
            row.encrypted_token = cipher().encrypt(data.access_token.encode()).decode()
        row.last_error = None
        audit(db, user, 'whatsapp.configure')
        db.commit()
        return status(user, db)


@router.delete('')
def disconnect(user=Depends(owner), db=Depends(get_db)):
    with locked():
        row = db.get(Settings, 1)
        if row:
            db.delete(row)
        for event in db.scalars(select(Event).where(Event.status == 'pending')):
            event.status, event.detail = 'cancelled', 'WhatsApp was disconnected.'
        # A new sender requires new customer enrollment.
        db.execute(delete(Customer))
        audit(db, user, 'whatsapp.disconnect')
        db.commit()
    return {'disconnected': True}


class CloudError(Exception):
    def __init__(self, detail, *, retry_after=None, ambiguous=False):
        self.detail, self.retry_after, self.ambiguous = detail, retry_after, ambiguous


def cloud(row, method, path, *, body=None, params=None):
    """Fixed provider origin; never return/log provider bodies or bearer tokens."""
    try:
        with httpx.Client(timeout=httpx.Timeout(20, connect=5), follow_redirects=False, trust_env=False) as client:
            response = client.request(method, 'https://graph.facebook.com/' + row.config['api_version'] + '/' + path,
                headers={'Authorization': 'Bearer ' + cipher().decrypt(row.encrypted_token.encode()).decode()},
                json=body, params=params)
    except httpx.HTTPError:
        raise CloudError('WhatsApp response was not confirmed. Check WhatsApp Manager before sending again.', ambiguous=method == 'POST') from None
    try:
        data = response.json()
    except ValueError:
        data = {}
    error = data.get('error', {}) if isinstance(data, dict) else {}
    code = error.get('code') if isinstance(error, dict) else None
    if response.status_code == 429 or code in (4, 17, 32, 613, 80007, 130429, 131048, 131056):
        try:
            wait = max(60, min(86400, int(response.headers.get('Retry-After', '300'))))
        except ValueError:
            wait = 300
        raise CloudError('WhatsApp requested a cooldown. Delivery is queued.', retry_after=wait)
    if not response.is_success or error:
        detail = ('WhatsApp access token is invalid or expired. Update the connection.' if code == 190 else
                  'WhatsApp rejected the notification. Check template approval, language, account permissions and recipient in WhatsApp Manager.')
        raise CloudError(detail, ambiguous=method == 'POST' and response.status_code >= 500)
    if not isinstance(data, dict):
        raise CloudError('WhatsApp returned an unexpected response.', ambiguous=method == 'POST')
    return data


@router.post('/check')
def check(user=Depends(owner), db=Depends(get_db)):
    with locked():
        row = configured(db)
        if not row:
            raise HTTPException(409, 'Save your WhatsApp and owner SAS4 settings first.')
        if row.retry_at and aware(row.retry_at) > now():
            raise HTTPException(429, 'WhatsApp requested a cooldown. Try after the displayed time.')
        try:
            phone = cloud(row, 'GET', row.config['phone_number_id'], params={'fields': 'id,display_phone_number'})
            if phone.get('id') != row.config['phone_number_id']:
                raise CloudError('WhatsApp did not verify this phone number ID.')
            for kind in KINDS:
                data = cloud(row, 'GET', row.config['business_account_id'] + '/message_templates',
                    params={'name': row.config[kind + '_template'], 'fields': 'name,status,language,components,parameter_format', 'limit': 100})
                templates = data.get('data')
                if not isinstance(templates, list):
                    raise CloudError('WhatsApp did not return the approved template list.')
                template = next((t for t in templates if isinstance(t, dict) and t.get('name') == row.config[kind + '_template']
                                 and t.get('language') == row.config['language'] and t.get('status') == 'APPROVED'), None)
                count = 3 if kind == 'recharge' else 2
                components = template.get('components', []) if template else []
                bodies = [c for c in components if c.get('type', '').upper() == 'BODY']
                if (not template or template.get('parameter_format', 'POSITIONAL') != 'POSITIONAL'
                        or len(bodies) != 1 or set(re.findall(r'\{\{(.*?)\}\}', bodies[0].get('text', ''))) != {str(n) for n in range(1, count + 1)}
                        or any(c.get('type', '').upper() not in ('BODY', 'FOOTER') for c in components)):
                    raise CloudError('Check ' + kind + ' template: approved language, body-only positional variables ' + ('1–3.' if count == 3 else '1–2.'))
            row.verified_at, row.last_error = now(), None
        except CloudError as exc:
            row.verified_at, row.last_error = None, exc.detail
            if exc.retry_after:
                row.retry_at = now() + timedelta(seconds=exc.retry_after)
            db.commit()
            raise HTTPException(502, exc.detail) from None
        audit(db, user, 'whatsapp.check')
        db.commit()
        return status(user, db)


def matching(pref, record):
    return bool(pref and pref.enabled and pref.customer_username == record.get('username')
                and pref.phone_hash == customers.phone_hash(record))


@router.get('/users/{customer_id}')
def customer_status(customer_id: int, user=Depends(customers.access), db=Depends(get_db)):
    record = customers.record_for(db, user, customer_id)
    row = configured(db)
    pref = db.get(Customer, (row.user_id, customer_id)) if row else None
    events = db.scalars(select(Event).where(Event.customer_id == customer_id,
        Event.user_id == (row.user_id if row else '')).order_by(Event.created_at.desc()).limit(10))
    return {'configured': bool(row), 'enabled': matching(pref, record), 'phone': customers.normalized_phone(record.get('phone')),
            'consent_at': pref.consent_at if pref and matching(pref, record) else None,
            'last_error': pref.last_error if pref else None,
            'events': [event_public(e) for e in events if (data := payload(e)).get('username') == record.get('username')
                       and data.get('phone_hash') == customers.phone_hash(record)]}


class CustomerInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    enabled: bool


@router.put('/users/{customer_id}')
def configure_customer(customer_id: int, data: CustomerInput, user=Depends(customers.editor), db=Depends(get_db)):
    with locked():
        row = configured(db)
        if not row:
            raise HTTPException(409, 'An owner must configure WhatsApp first.')
        record = customers.record_for(db, user, customer_id)
        # The selected owner's SAS4 scope must refer to the same customer.
        sender_record = customers.record_for(db, db.get(User, row.user_id), customer_id)
        if record.get('username') != sender_record.get('username') or customers.phone_hash(record) != customers.phone_hash(sender_record):
            raise HTTPException(409, 'The owner and customer SAS4 records do not match.')
        if not record.get('username') or not customers.phone_hash(record):
            raise HTTPException(422, 'Save a valid customer phone in ISP card first.')
        pref = db.get(Customer, (row.user_id, customer_id)) or Customer(user_id=row.user_id, customer_id=customer_id)
        pref.enabled, pref.customer_username, pref.phone_hash = data.enabled, record['username'], customers.phone_hash(record)
        pref.version, pref.next_check, pref.last_error = uid(), now(), None
        pref.consent_at = now() if data.enabled else None
        db.add(pref)
        audit(db, user, 'whatsapp.customer.enable' if data.enabled else 'whatsapp.customer.disable', str(customer_id))
        db.commit()
        return customer_status(customer_id, user, db)


def payload(event):
    return json.loads(cipher().decrypt(event.encrypted_payload.encode()))


def queue(db, row, pref, actor, kind, key, record, expiration, reference=''):
    event_id = hashlib.sha256(f'whatsapp:{row.user_id}:{pref.customer_id}:{record["username"]}:{kind}:{key}'.encode()).hexdigest()
    if db.get(Event, event_id):
        return
    connection = db.get(SAS4UserConnection, actor.id)
    data = {'username': record['username'], 'phone_hash': customers.phone_hash(record),
            'expiration': str(expiration or ''), 'reference': str(reference)[:160],
            'actor_connection': connection.username if connection else None}
    db.add(Event(id=event_id, user_id=row.user_id, actor_id=actor.id, customer_id=pref.customer_id,
        version=row.version, customer_version=pref.version, kind=kind,
        encrypted_payload=cipher().encrypt(json.dumps(data).encode()).decode()))


def enqueue(db, actor, customer_id, method, transaction_id, receipt=None):
    row = configured(db)
    if not row or not row.verified_at or not row.config['recharge'] or method not in METHODS or not customers.allowed(db, actor, True):
        return
    pref = db.get(Customer, (row.user_id, customer_id))
    if not pref or not pref.enabled:
        return
    record = customers.record_for(db, actor, customer_id)
    if not matching(pref, record):
        return
    receipt = receipt or {}
    if receipt.get('username') and (receipt['username'] != record.get('username') or receipt.get('phone_hash') != customers.phone_hash(record)):
        return
    queue(db, row, pref, actor, 'recharge', f'{actor.id}:{method}:{transaction_id}', record,
          receipt.get('expiration') or record.get('expiration'), transaction_id)


def activation(db, actor, customer_id, method, transaction_id, receipt=None):
    try:
        with db.begin_nested():
            enqueue(db, actor, customer_id, method, transaction_id, receipt)
            db.flush()
    except Exception:
        audit(db, actor, 'whatsapp.queue_failed', str(customer_id))


def expiry_kind(expiry):
    remaining = expiry - now()
    if timedelta(days=2) < remaining <= timedelta(days=3):
        return 'expiry_3days'
    if -timedelta(days=1) < remaining <= timedelta(0):
        return 'expired'
    return None


def scan_expiry(db, row):
    if not row.verified_at or not (row.config['expiry_3days'] or row.config['expired']):
        return
    pref = db.scalar(select(Customer).where(Customer.user_id == row.user_id, Customer.enabled.is_(True),
        Customer.next_check <= now()).order_by(Customer.next_check).limit(1))
    if not pref:
        return
    try:
        actor = db.get(User, row.user_id)
        record = customers.record_for(db, actor, pref.customer_id)
        if not matching(pref, record):
            pref.enabled, pref.last_error = False, 'Customer phone or account changed. Confirm permission again.'
        else:
            expiry = customers.expiry_time(record.get('expiration'), row.config['timezone'])
            kind = expiry_kind(expiry) if expiry else None
            if kind and row.config[kind] and record.get('enabled') is not False:
                queue(db, row, pref, actor, kind, expiry.astimezone(timezone.utc).isoformat(), record, record['expiration'])
            pref.last_error = None
        pref.last_checked, pref.next_check = now(), now() + timedelta(hours=1)
    except Exception:
        pref.last_error, pref.next_check = 'Could not check customer expiry in SAS4.', now() + timedelta(minutes=5)
    db.commit()


def cancel(db, event, detail):
    event.status, event.detail = 'cancelled', detail
    db.commit()


def deliver(db, event):
    if event.status != 'pending':
        return
    row = configured(db)
    pref = db.get(Customer, (event.user_id, event.customer_id))
    actor = db.get(User, event.actor_id) if event.actor_id else None
    if (not row or not row.verified_at or row.user_id != event.user_id or row.version != event.version
            or not row.config[event.kind] or not pref or not pref.enabled or pref.version != event.customer_version
            or not customers.allowed(db, actor, True)):
        return cancel(db, event, 'Notification settings or customer permission changed.')
    if now() - aware(event.created_at) > timedelta(days=1):
        return cancel(db, event, 'The notification is more than one day old.')
    if row.retry_at and aware(row.retry_at) > now():
        event.next_attempt = row.retry_at
        db.commit()
        return
    data = payload(event)
    connection = db.get(SAS4UserConnection, actor.id)
    if not connection or connection.username != data['actor_connection']:
        return cancel(db, event, 'The SAS4 connection changed.')
    try:
        record = customers.record_for(db, actor, event.customer_id)
        if not matching(pref, record) or data['username'] != record.get('username') or data['phone_hash'] != customers.phone_hash(record):
            return cancel(db, event, 'The customer phone or account changed.')
        if actor.id != row.user_id:
            sender_record = customers.record_for(db, db.get(User, row.user_id), event.customer_id)
            if not matching(pref, sender_record):
                return cancel(db, event, 'The selected owner no longer has the same customer record.')
        expiry = customers.expiry_time(data['expiration'], row.config['timezone'])
        if event.kind != 'recharge':
            current_expiry = customers.expiry_time(record.get('expiration'), row.config['timezone'])
            if record.get('enabled') is False or not expiry or expiry != current_expiry or expiry_kind(expiry) != event.kind:
                return cancel(db, event, 'Customer expiry changed or notification is no longer due.')
        # Missing expiry must not fabricate a successful renewal date.
        if not expiry:
            return cancel(db, event, 'No valid service expiry was available for this notification.')
        values = [data['username'], expiry.astimezone(ZoneInfo(row.config['timezone'])).strftime('%Y-%m-%d %H:%M')]
        if event.kind == 'recharge':
            values.append(data['reference'])
        body = {'messaging_product': 'whatsapp', 'recipient_type': 'individual',
                'to': customers.normalized_phone(record['phone']), 'type': 'template',
                'template': {'name': row.config[event.kind + '_template'], 'language': {'code': row.config['language']},
                    'components': [{'type': 'body', 'parameters': [{'type': 'text', 'text': ' '.join(str(v).split())[:160]} for v in values]}]}}
    except Exception:
        event.attempts += 1
        event.status = 'failed' if event.attempts >= 5 else 'pending'
        event.detail, event.next_attempt = 'Customer access could not be verified in SAS4.', now() + timedelta(minutes=5)
        db.commit()
        return
    # Persist before the HTTP request. A timeout/crash must not duplicate a receipt.
    event.status, event.detail = 'unconfirmed', 'WhatsApp submission may have started; automatic repeat is disabled.'
    event.attempts += 1
    db.commit()
    try:
        response = cloud(row, 'POST', row.config['phone_number_id'] + '/messages', body=body)
        messages = response.get('messages')
        if not isinstance(messages, list) or not messages or not isinstance(messages[0].get('id'), str):
            raise CloudError('WhatsApp did not confirm acceptance. Check WhatsApp Manager.', ambiguous=True)
        event.status, event.accepted_at, event.message_id = 'accepted', now(), messages[0]['id'][:256]
        event.detail, row.last_error = 'WhatsApp accepted the message; delivery to the phone is not confirmed here.', None
    except CloudError as exc:
        event.detail, row.last_error = exc.detail, exc.detail
        if exc.retry_after:
            row.retry_at = now() + timedelta(seconds=exc.retry_after)
            event.next_attempt = row.retry_at
            event.status = 'pending' if event.attempts < 5 else 'failed'
        elif not exc.ambiguous:
            event.status = 'failed'
    except Exception:
        event.detail = 'WhatsApp response was not confirmed. Check WhatsApp Manager; no automatic retry.'
    db.commit()


def tick():
    with locked(), SessionLocal() as db:
        row = configured(db)
        if row:
            scan_expiry(db, row)
        event = db.scalar(select(Event).where(Event.status == 'pending', Event.next_attempt <= now()).order_by(Event.next_attempt).limit(1))
        if event:
            deliver(db, event)
        db.execute(delete(Event).where(Event.created_at < now() - timedelta(days=90), Event.status != 'pending')
                   .execution_options(synchronize_session=False))
        db.commit()


async def worker():
    while True:
        try:
            await asyncio.to_thread(tick)
        except Exception:
            pass  # No credentials or customer data in logs.
        await asyncio.sleep(5)
