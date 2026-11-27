"""Twilio WhatsApp service notifications with customer consent and durable delivery state."""
from .section_access import has_capability
import asyncio
import hashlib
import json
import re
from contextlib import contextmanager
from datetime import timedelta, timezone
from zoneinfo import ZoneInfo

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select, delete
from . import customer_telegram as customers
from .db import get_db, SessionLocal
from .models import (TwilioWhatsAppSettings as Settings, TwilioWhatsAppCustomer as Customer,
                     TwilioWhatsAppEvent as Event, SAS4UserConnection, User, now, uid, audit)
from .security import owner, cipher, aware

router = APIRouter(prefix='/api/integrations/twilio-whatsapp', tags=['Twilio WhatsApp'])
KINDS = ('recharge', 'expiry_3days', 'expired')
METHODS = {'card', 'credit', 'extend', 'fib', 'fastpay'}
DEFAULTS = {'account_sid': '', 'from_number': '', 'messaging_service_sid': '', 'timezone': 'Asia/Baghdad',
            **{kind: False for kind in KINDS}, **{kind + '_content_sid': '' for kind in KINDS}}


class SettingsInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    account_sid: str = Field(pattern=r'^AC[0-9a-fA-F]{32}$')
    auth_token: str = Field(default='', max_length=128)
    from_number: str = Field(default='', pattern=r'^(?:\+[1-9][0-9]{7,14})?$')
    messaging_service_sid: str = Field(default='', pattern=r'^(?:MG[0-9a-fA-F]{32})?$')
    timezone: str = Field(default='Asia/Baghdad', max_length=64)
    recharge: bool = False
    expiry_3days: bool = False
    expired: bool = False
    recharge_content_sid: str = Field(pattern=r'^HX[0-9a-fA-F]{32}$')
    expiry_3days_content_sid: str = Field(pattern=r'^HX[0-9a-fA-F]{32}$')
    expired_content_sid: str = Field(pattern=r'^HX[0-9a-fA-F]{32}$')

    @field_validator('timezone')
    @classmethod
    def valid_zone(cls, value):
        try:
            ZoneInfo(value)
        except (ValueError, KeyError):
            raise ValueError('Invalid timezone') from None
        return value

    @field_validator('auth_token')
    @classmethod
    def valid_token(cls, value):
        if value and not re.fullmatch(r'[0-9a-fA-F]{32}', value):
            raise ValueError('Invalid Twilio Auth Token')
        return value

    @model_validator(mode='after')
    def valid_sender(self):
        if bool(self.from_number) == bool(self.messaging_service_sid):
            raise ValueError('Choose a Twilio phone number or a Messaging Service SID')
        return self


@contextmanager
def locked():
    from .api import cache
    from redis.exceptions import RedisError
    lock = cache.lock('twilio_whatsapp:operations', timeout=300, blocking=False)
    try:
        acquired = lock.acquire(blocking=False)
    except RedisError:
        raise HTTPException(503, 'Twilio WhatsApp operation protection is unavailable.') from None
    if not acquired:
        raise HTTPException(409, 'Twilio WhatsApp is busy. Try again shortly.')
    try:
        yield
    finally:
        if lock.owned():
            lock.release()


def configured(db):
    row = db.get(Settings, 1)
    user = db.get(User, row.user_id) if row else None
    connection = db.get(SAS4UserConnection, row.user_id) if row else None
    return row if (user and user.active and has_capability(user, 'whatsapp', db, write=True) and connection
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
        if not data.auth_token and (not row or row.user_id != user.id or row.config.get('account_sid') != data.account_sid):
            raise HTTPException(422, 'Enter your Twilio Auth Token.')
        config = data.model_dump(exclude={'auth_token'})
        same = bool(row and row.user_id == user.id and row.sas4_username == connection.username
                    and not data.auth_token and all(row.config.get(k) == v for k, v in config.items() if k not in KINDS))
        if any(config[k] for k in KINDS) and not (same and row.verified_at):
            raise HTTPException(409, 'Save with notifications off, then check the connection and templates before enabling notifications.')
        if row is None:
            row = Settings(id=1)
            db.add(row)
        if not same:
            row.verified_at = None
            row.version = uid()
            row.retry_at = None
        row.user_id, row.sas4_username = user.id, connection.username
        row.config = config
        if data.auth_token:
            row.encrypted_token = cipher().encrypt(data.auth_token.encode()).decode()
        row.last_error = None
        audit(db, user, 'twilio_whatsapp.configure')
        db.commit()
        return status(user, db)


@router.delete('')
def disconnect(user=Depends(owner), db=Depends(get_db)):
    with locked():
        row = db.get(Settings, 1)
        if row:
            db.delete(row)
        for event in db.scalars(select(Event).where(Event.status == 'pending')):
            event.status, event.detail = 'cancelled', 'Twilio WhatsApp was disconnected.'
        # A new sender requires new customer enrollment.
        db.execute(delete(Customer))
        audit(db, user, 'twilio_whatsapp.disconnect')
        db.commit()
    return {'disconnected': True}


class CloudError(Exception):
    def __init__(self, detail, *, retry_after=None, ambiguous=False):
        self.detail, self.retry_after, self.ambiguous = detail, retry_after, ambiguous


def cloud(row, method, path, *, body=None, params=None, messaging=False, content=False):
    """Twilio-only origins, Basic authentication, form-encoded WhatsApp; redact errors."""
    origin = ('https://content.twilio.com/v1/' if content else
              'https://messaging.twilio.com/v1/' if messaging else 'https://api.twilio.com/2010-04-01/')
    try:
        token = cipher().decrypt(row.encrypted_token.encode()).decode()
        with httpx.Client(timeout=httpx.Timeout(20, connect=5), follow_redirects=False, trust_env=False) as client:
            response = client.request(method, origin + path,
                auth=(row.config['account_sid'], token), data=body, params=params)
    except httpx.HTTPError:
        raise CloudError('Twilio response was not confirmed. Check Twilio Messaging logs before sending again.', ambiguous=method == 'POST') from None
    except Exception:
        raise CloudError('Twilio credentials cannot be read. Save the Auth Token again.') from None
    if response.status_code == 429:
        try:
            wait = max(60, min(86400, int(response.headers.get('Retry-After', '300'))))
        except ValueError:
            wait = 300
        raise CloudError('Twilio requested a cooldown. WhatsApp delivery is queued.', retry_after=wait)
    if not response.is_success:
        detail = ('Twilio authentication failed. Check the Account SID and Auth Token.' if response.status_code in (401, 403) else
                  'Twilio rejected the request. Check the WhatsApp sender, recipient, template approval and Messaging logs in Twilio Console.')
        raise CloudError(detail, ambiguous=method == 'POST' and response.status_code >= 500)
    try:
        data = response.json()
    except ValueError:
        data = None
    if not isinstance(data, dict):
        raise CloudError('Twilio returned an unexpected response.', ambiguous=method == 'POST')
    return data


def account_path(row):
    return 'Accounts/' + row.config['account_sid']


@router.post('/check')
def check(user=Depends(owner), db=Depends(get_db)):
    with locked():
        row = configured(db)
        if not row:
            raise HTTPException(409, 'Save Twilio WhatsApp and your SAS4 connection first.')
        if row.retry_at and aware(row.retry_at) > now():
            raise HTTPException(429, 'Twilio requested a cooldown. Try after the displayed time.')
        try:
            account = cloud(row, 'GET', account_path(row) + '.json')
            if account.get('sid') != row.config['account_sid'] or account.get('status') != 'active':
                raise CloudError('Twilio did not confirm an active account for this Account SID.')
            service = row.config.get('messaging_service_sid')
            if service:
                sender = cloud(row, 'GET', 'Services/' + service, messaging=True)
                if sender.get('sid') != service or sender.get('account_sid') != row.config['account_sid']:
                    raise CloudError('Twilio did not verify this Messaging Service. Check its account and WhatsApp sender pool.')
            for kind in KINDS:
                sid = row.config[kind + '_content_sid']
                template = cloud(row, 'GET', 'Content/' + sid, content=True)
                approval = cloud(row, 'GET', 'Content/' + sid + '/ApprovalRequests', content=True)
                state = approval.get('whatsapp')
                types = template.get('types')
                text = types.get('twilio/text') if isinstance(types, dict) else None
                count = 3 if kind == 'recharge' else 2
                expected = {str(n) for n in range(1, count + 1)}
                if (template.get('sid') != sid or template.get('account_sid') != row.config['account_sid']
                        or not isinstance(state, dict) or str(state.get('status')).lower() != 'approved'
                        or not isinstance(text, dict) or set(types) != {'twilio/text'}
                        or not isinstance(text.get('body'), str)
                        or {v.strip() for v in re.findall(r'\{\{(.*?)\}\}', text['body'])} != expected
                        or not isinstance(template.get('variables'), dict) or set(template['variables']) != expected):
                    raise CloudError('Check the ' + kind + ' Content SID: use an approved WhatsApp text template in this Twilio account with variables '
                                     + ('1–3.' if count == 3 else '1–2.'))
            row.verified_at, row.last_error, row.retry_at = now(), None, None
        except CloudError as exc:
            row.verified_at, row.last_error = None, exc.detail
            if exc.retry_after:
                row.retry_at = now() + timedelta(seconds=exc.retry_after)
            db.commit()
            raise HTTPException(502, exc.detail) from None
        audit(db, user, 'twilio_whatsapp.check')
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
            raise HTTPException(409, 'An owner must configure Twilio WhatsApp first.')
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
        audit(db, user, 'twilio_whatsapp.customer.enable' if data.enabled else 'twilio_whatsapp.customer.disable', str(customer_id))
        db.commit()
        return customer_status(customer_id, user, db)


def payload(event):
    return json.loads(cipher().decrypt(event.encrypted_payload.encode()))


def queue(db, row, pref, actor, kind, key, record, expiration, reference=''):
    event_id = hashlib.sha256(f'twilio_whatsapp:{row.user_id}:{pref.customer_id}:{record["username"]}:{kind}:{key}'.encode()).hexdigest()
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
        audit(db, actor, 'twilio_whatsapp.queue_failed', str(customer_id))


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
        variables = {str(index): ' '.join(str(value).split()) for index, value in enumerate(values, 1)}
        if any(not value for value in variables.values()):
            return cancel(db, event, 'A required WhatsApp template value is missing.')
        body = {'To': 'whatsapp:+' + customers.normalized_phone(record['phone']),
                'ContentSid': row.config[event.kind + '_content_sid'],
                'ContentVariables': json.dumps(variables, ensure_ascii=False), 'ValidityPeriod': '3600'}
        if row.config.get('messaging_service_sid'):
            body['MessagingServiceSid'] = row.config['messaging_service_sid']
        else:
            body['From'] = 'whatsapp:' + row.config['from_number']

    except Exception:
        event.attempts += 1
        event.status = 'failed' if event.attempts >= 5 else 'pending'
        event.detail, event.next_attempt = 'Customer access could not be verified in SAS4.', now() + timedelta(minutes=5)
        db.commit()
        return
    # Persist before the HTTP request. A timeout/crash must not duplicate a receipt.
    event.status, event.detail = 'unconfirmed', 'Twilio WhatsApp submission may have started; automatic repeat is disabled.'
    event.attempts += 1
    db.commit()
    try:
        response = cloud(row, 'POST', account_path(row) + '/Messages.json', body=body)
        message_id = response.get('sid')
        if (not isinstance(message_id, str) or not re.fullmatch(r'SM[0-9a-fA-F]{32}', message_id)
                or response.get('account_sid') != row.config['account_sid']):
            raise CloudError('Twilio did not confirm WhatsApp acceptance. Check Twilio Messaging logs.', ambiguous=True)
        event.message_id = message_id
        if response.get('status') in ('failed', 'undelivered', 'canceled'):
            raise CloudError('Twilio could not deliver the WhatsApp. Review its Messaging logs; no automatic resend.')
        if response.get('status') not in ('accepted', 'queued', 'sending', 'sent', 'delivered', 'read') or response.get('error_code') is not None:
            raise CloudError('Twilio returned an unconfirmed WhatsApp state. Review its Messaging logs; no automatic resend.', ambiguous=True)
        event.status, event.accepted_at = ('delivered' if response['status'] in ('delivered', 'read') else 'accepted'), now()
        event.next_attempt = now() + timedelta(minutes=1)
        event.detail = ('Twilio reports WhatsApp delivery.' if event.status == 'delivered' else
                        'Twilio accepted the WhatsApp; delivery to the phone is pending confirmation.')
        row.last_error = None

    except CloudError as exc:
        event.detail, row.last_error = exc.detail, exc.detail
        if exc.retry_after:
            row.retry_at = now() + timedelta(seconds=exc.retry_after)
            event.next_attempt = row.retry_at
            event.status = 'pending' if event.attempts < 5 else 'failed'
        elif not exc.ambiguous:
            event.status = 'failed'
    except Exception:
        event.detail = 'Twilio WhatsApp response was not confirmed. Check Twilio Messaging logs; no automatic retry.'
    db.commit()


def refresh_delivery(db, row, event):
    """Read receipts from Twilio without requiring an incoming webhook or resending."""
    if (not row or row.user_id != event.user_id or row.version != event.version
            or not re.fullmatch(r'SM[0-9a-fA-F]{32}', event.message_id or '')):
        event.next_attempt = now() + timedelta(days=2)
        db.commit()
        return
    if row.retry_at and aware(row.retry_at) > now():
        event.next_attempt = row.retry_at
        db.commit()
        return
    event.next_attempt = now() + timedelta(minutes=5)
    try:
        data = cloud(row, 'GET', account_path(row) + '/Messages/' + event.message_id + '.json')
        if data.get('sid') != event.message_id or data.get('account_sid') != row.config['account_sid']:
            raise CloudError('Twilio could not verify the WhatsApp delivery receipt.')
        if data.get('status') in ('delivered', 'read'):
            event.status, event.detail = 'delivered', 'Twilio reports WhatsApp delivery.'
        elif data.get('status') in ('failed', 'undelivered', 'canceled'):
            event.status, event.detail = 'failed', 'Twilio reports that the WhatsApp was not delivered. Review its Messaging logs; no automatic resend.'
        elif data.get('status') == 'sent':
            event.detail = 'Twilio sent the WhatsApp to the carrier; phone delivery is not yet confirmed.'
    except CloudError as exc:
        event.detail = 'WhatsApp was accepted; delivery status is currently unavailable. Check Twilio Messaging logs.'
        if exc.retry_after:
            row.retry_at = event.next_attempt = now() + timedelta(seconds=exc.retry_after)
    db.commit()


def tick():
    with locked(), SessionLocal() as db:
        row = configured(db)
        if row:
            scan_expiry(db, row)
        event = db.scalar(select(Event).where(Event.status == 'pending', Event.next_attempt <= now()).order_by(Event.next_attempt).limit(1))
        if event:
            deliver(db, event)
        receipt = db.scalar(select(Event).where(Event.status == 'accepted', Event.next_attempt <= now(),
            Event.created_at >= now() - timedelta(days=1)).order_by(Event.next_attempt).limit(1))
        if receipt:
            refresh_delivery(db, row, receipt)
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
