from .section_access import has_capability
"""Automatic receipts for confirmed recharges, sent through the selected owner account."""
import hashlib
import json
from string import Formatter
from types import SimpleNamespace
from datetime import timedelta, timezone
from typing import Literal
from zoneinfo import ZoneInfo
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select, delete
from telethon import errors, functions, types
from . import customer_telegram as customers, telegram_account as accounts
from .db import get_db
from .models import (RechargeTelegramSettings as Settings, RechargeTelegramEvent as Event,
                     RechargeTelegramTemplate as MessageTemplate,
                     TelegramExpirySchedule as ExpirySchedule,
                     TelegramAccount, SAS4UserConnection, User, now, uid, audit)
from .security import cipher, aware

router = APIRouter(prefix='/api/integrations/recharge-telegram', tags=['Recharge Telegram'])
METHODS = {'card', 'credit', 'extend', 'fib', 'fastpay'}
EXPIRY_KINDS = {'expiry_3days', 'expired'}
RECEIPT_FIELDS = {'username', 'phone_hash', 'profile', 'expiration', 'reference', 'card',
                  'extension', 'service_price', 'currency', 'amount', 'recharge_cost'}


class SettingsInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    enabled: bool
    language: Literal['en', 'ku', 'ar'] = 'en'
    timezone: str = Field(default='Asia/Baghdad', max_length=64)

    @field_validator('timezone')
    @classmethod
    def zone(cls, value):
        try:
            ZoneInfo(value)
        except (ValueError, KeyError):
            raise ValueError('Enter a valid timezone, for example Asia/Baghdad')
        return value


def public(selection, user):
    return {'enabled': bool(selection and selection.enabled),
            'selected_owner': bool(selection and selection.user_id == user.id),
            'language': selection.language if selection else 'en',
            'timezone': selection.timezone if selection else 'Asia/Baghdad'}


def language_for(db, fallback='en'):
    # This read is also used while a new customer link is being initialized.
    with db.no_autoflush:
        selection = db.get(Settings, 1)
    return selection.language if selection else fallback


def expiry_enabled(db):
    schedule = db.get(ExpirySchedule, 1)
    return bool(schedule and schedule.enabled)


class ExpiryInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    enabled: bool


@router.get('/expiry')
def expiry_status(user=Depends(accounts.owner), db=Depends(get_db)):
    schedule = db.get(ExpirySchedule, 1)
    return {'enabled': bool(schedule and schedule.enabled),
            'last_checked': schedule.last_checked if schedule else None,
            'last_error': schedule.last_error if schedule else None}


@router.put('/expiry')
def configure_expiry(data: ExpiryInput, user=Depends(accounts.owner), db=Depends(get_db)):
    with accounts.locked('recharge-settings'):
        selection = db.get(Settings, 1)
        if data.enabled and not selection:
            raise HTTPException(409, 'Save the owner Telegram notification settings first.')
        with accounts.locked(selection.user_id if selection else user.id):
            if data.enabled:
                sender = db.get(User, selection.user_id)
                state = accounts.read(db.get(TelegramAccount, selection.user_id))
                connection = db.get(SAS4UserConnection, selection.user_id)
                if (not sender or not sender.active or not has_capability(sender, 'telegram_bot', db, write=True) or not connection
                        or connection.username != selection.sas4_username
                        or accounts.public(state)['stage'] != 'connected' or state['profile']['id'] != selection.sender_id):
                    raise HTTPException(409, 'Reconnect the selected owner Telegram and SAS4 accounts first.')
            schedule = db.get(ExpirySchedule, 1) or ExpirySchedule(id=1)
            schedule.enabled, schedule.page, schedule.next_check = data.enabled, 1, now()
            schedule.last_error = None
            db.add(schedule)
            audit(db, user, 'telegram_expiry.enabled' if data.enabled else 'telegram_expiry.disabled')
            db.commit()
            return expiry_status(user, db)


@router.put('/language')
def save_language(data: customers.LinkInput, user=Depends(accounts.owner), db=Depends(get_db)):
    with accounts.locked('recharge-settings'):
        selection = db.get(Settings, 1)
        with accounts.locked(selection.user_id if selection else user.id):
            if not selection:
                return save_settings(SettingsInput(enabled=False, language=data.language), user, db)
            # Changing language never enables sending or changes the selected owner.
            selection.language = data.language
            audit(db, user, 'telegram_recharge.language')
            db.commit()
            return public(selection, user)


@router.get('')
def status(user=Depends(accounts.owner), db=Depends(get_db)):
    return public(db.get(Settings, 1), user)


@router.put('')
def configure(data: SettingsInput, user=Depends(accounts.owner), db=Depends(get_db)):
    with accounts.locked('recharge-settings'):
        selection = db.get(Settings, 1)
        # Changing/disabling a sender cannot race an in-flight receipt from it.
        with accounts.locked(selection.user_id if selection else user.id):
            return save_settings(data, user, db)


def save_settings(data, user, db):
    selection = db.get(Settings, 1)
    if not data.enabled and selection:
        selection.enabled, selection.version = False, uid()
        selection.language, selection.timezone = data.language, data.timezone
        audit(db, user, 'telegram_recharge.disabled')
        db.commit()
        return public(selection, user)
    account = db.get(TelegramAccount, user.id)
    state = accounts.read(account)
    connection = db.get(SAS4UserConnection, user.id)
    if accounts.public(state)['stage'] != 'connected' or not connection:
        raise HTTPException(409, 'Connect your Telegram account and owner SAS4 account first.')
    sender_id = state['profile']['id']
    if not selection:
        selection = Settings(id=1)
        db.add(selection)
    if (not selection.enabled or selection.user_id != user.id or selection.sender_id != sender_id
            or selection.sas4_username != connection.username):
        selection.version = uid()
    selection.user_id, selection.sender_id = user.id, sender_id
    selection.enabled, selection.sas4_username = data.enabled, connection.username
    selection.language, selection.timezone = data.language, data.timezone
    audit(db, user, 'telegram_recharge.enabled' if data.enabled else 'telegram_recharge.disabled')
    db.commit()
    return public(selection, user)


def payload(event):
    return json.loads(cipher().decrypt(event.encrypted_payload.encode()))


def enqueue(db, actor, customer_id, method, transaction_id, receipt=None):
    """Return True when account delivery is selected, preventing duplicate bot receipts."""
    selection = db.get(Settings, 1)
    if not selection or not selection.enabled or method not in METHODS:
        return False
    if not customers.allowed(db, actor, True):
        return True
    event_id = hashlib.sha256(f'recharge:{actor.id}:{customer_id}:{method}:{transaction_id}'.encode()).hexdigest()
    if db.get(Event, event_id):
        return True
    receipt = {key: str(value)[:160] for key, value in (receipt or {}).items()
               if key in RECEIPT_FIELDS and value is not None and isinstance(value, (str, int, float))}
    if not receipt.get('username') or not receipt.get('phone_hash'):
        record = customers.record_for(db, actor, customer_id)
        receipt['username'], receipt['phone_hash'] = record.get('username'), customers.phone_hash(record)
    receipt['reference'] = str(transaction_id)[:80]
    language = selection.language
    connection = db.get(SAS4UserConnection, actor.id)
    data = {'receipt': receipt, 'language': language, 'timezone': selection.timezone,
            'actor_connection': connection.username if connection else None}
    event = Event(id=event_id, user_id=selection.user_id, actor_id=actor.id,
        customer_id=customer_id, version=selection.version, kind=method,
        encrypted_payload=cipher().encrypt(json.dumps(data).encode()).decode())
    if not receipt.get('username') or not receipt.get('phone_hash'):
        event.status, event.detail = 'skipped', 'No valid customer phone was saved at recharge.'
    db.add(event)
    return True


LABELS = {
    'en': {'title': 'Recharge successful', 'method': 'Method', 'user': 'Account', 'profile': 'Service plan',
           'expiration': 'New expiry', 'reference': 'Transaction', 'card': 'Card', 'extension': 'Extension',
           'amount': 'Recharge cost', 'service_price': 'Service price', 'date': 'Recharge time',
           'card_method': 'Card PIN', 'credit': 'Account balance', 'extend': 'Service extension',
           'fib': 'FIB', 'fastpay': 'FastPay'},
    'ar': {'title': 'تمت إعادة التعبئة بنجاح', 'method': 'الطريقة', 'user': 'الحساب', 'profile': 'باقة الخدمة',
           'expiration': 'تاريخ الانتهاء الجديد', 'reference': 'رقم المعاملة', 'card': 'البطاقة', 'extension': 'التمديد',
           'amount': 'تكلفة إعادة التعبئة', 'service_price': 'سعر الخدمة', 'date': 'وقت التعبئة',
           'card_method': 'بطاقة التعبئة', 'credit': 'رصيد الحساب', 'extend': 'تمديد الخدمة', 'fib': 'FIB', 'fastpay': 'FastPay'},
    'ku': {'title': 'تژیکرن ب سەرکەفتی هاتە ئەنجامدان', 'method': 'ڕێک', 'user': 'هەژمار', 'profile': 'پلانا خزمەتگوزاریێ',
           'expiration': 'مێژوویا دوماهیێ یا نوو', 'reference': 'ژمارا مامەلەیێ', 'card': 'کارت', 'extension': 'درێژکرن',
           'amount': 'بهایێ تژیکرنێ', 'service_price': 'بهایێ خزمەتگوزاریێ', 'date': 'دەمێ تژیکرنێ',
           'card_method': 'کودێ کارتێ', 'credit': 'باڵانسا هەژمارێ', 'extend': 'درێژکرنا خزمەتگوزاریێ', 'fib': 'FIB', 'fastpay': 'FastPay'},
}

EXPIRY_LABELS = {
    'en': {'expiry_3days': 'Your service expires in 3 days.', 'expired': 'Your service has expired.',
           'expiration': 'Service expiry', 'date': 'Notification time'},
    'ar': {'expiry_3days': 'تنتهي خدمتك خلال 3 أيام.', 'expired': 'انتهت صلاحية خدمتك.',
           'expiration': 'تاريخ انتهاء الخدمة', 'date': 'وقت الإشعار'},
    'ku': {'expiry_3days': 'خزمەتگوزاریا تە پشتی ٣ ڕۆژان بدوماهی دهێت.', 'expired': 'خزمەتگوزاریا تە بدوماهی هات.',
           'expiration': 'مێژوویا دوماهیێ', 'date': 'دەمێ ئاگەهداریێ'},
}


def message_values(event, data):
    labels = LABELS.get(data.get('language'), LABELS['en'])
    if event.kind in EXPIRY_KINDS:
        labels = {**labels, **EXPIRY_LABELS.get(data.get('language'), EXPIRY_LABELS['en'])}
    receipt = data['receipt']
    zone = ZoneInfo(data['timezone'])
    values = {key: '' for key in PLACEHOLDERS}
    values['method'] = labels['card_method' if event.kind == 'card' else event.kind] if event.kind != 'test' else 'Test'
    lines = []
    def clean(value):
        return ' '.join(str(value).split()).encode('utf-16-le')[:320].decode('utf-16-le', errors='ignore')
    values['currency'] = clean(receipt.get('currency') or '')
    for key in ('username', 'profile', 'extension', 'card', 'recharge_cost', 'service_price', 'expiration', 'reference'):
        value = receipt.get(key)
        if value in (None, ''):
            continue
        if key == 'expiration':
            expiry = customers.expiry_time(value, data['timezone'])
            if not expiry:
                continue
            value = expiry.astimezone(zone).strftime('%Y-%m-%d %H:%M')
        values[key] = clean(value)
        if key in ('recharge_cost', 'service_price') and receipt.get('currency'):
            value = clean(value) + ' ' + clean(receipt['currency'])
        label = 'user' if key == 'username' else 'amount' if key == 'recharge_cost' else key
        lines.append(labels[label] + ': ' + clean(value))
    values['date'] = aware(event.created_at).astimezone(zone).strftime('%Y-%m-%d %H:%M')
    lines.append(labels['date'] + ': ' + values['date'])
    values['details'] = '\n'.join(lines)
    values.setdefault('amount', values['recharge_cost'])  # Legacy saved templates.
    return values


PLACEHOLDERS = ('username', 'method', 'profile', 'expiration', 'reference', 'card',
                'extension', 'recharge_cost', 'service_price', 'currency', 'date', 'details')
TemplateLanguage = Literal['en', 'ku', 'ar']
TemplateKind = Literal['card', 'credit', 'extend', 'fib', 'fastpay', 'test', 'expiry_3days', 'expired']


def default_template(language, kind):
    if kind == 'test':
        return accounts.TEST_MESSAGES[language]
    if kind in EXPIRY_KINDS:
        return 'AirLink\n' + EXPIRY_LABELS[language][kind] + '\n{details}'
    labels = LABELS[language]
    return 'AirLink\n' + labels['title'] + '\n' + labels['method'] + ': {method}\n{details}'


def canonical_template(text):
    """Rename legacy fields without changing escaped literal braces."""
    result = []
    for literal, field, spec, conversion in Formatter().parse(text):
        result.append(literal.replace('{', '{{').replace('}', '}}'))
        if field is not None:
            field = 'recharge_cost' if field == 'amount' else field
            result.append('{' + field + ('!' + conversion if conversion else '')
                          + (':' + spec if spec else '') + '}')
    return ''.join(result)


def validate_template(text):
    text = canonical_template(text)
    if not text.strip() or len(text) > 1500 or any(ord(c) < 32 and c not in '\n\t\r' for c in text):
        raise ValueError('Enter a notification between 1 and 1500 characters.')
    try:
        parts = list(Formatter().parse(text))
    except ValueError:
        raise ValueError('Check the placeholder braces.') from None
    for _, field, spec, conversion in parts:
        if field is not None and (field not in PLACEHOLDERS or spec or conversion):
            raise ValueError('Use only the listed placeholders, without formatting or attribute access.')
    # Bound expansion, including emoji, without silently truncating a receipt.
    worst = {key: 'x' * (2500 if key == 'details' else 160) for key in PLACEHOLDERS}
    if len(text.format_map(worst).encode('utf-16-le')) // 2 > 4000:
        raise ValueError('The message could be too long after inserting details. Shorten it or remove repeated placeholders.')
    return text


class TemplateInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    text: str = Field(min_length=1, max_length=1500)

    @field_validator('text')
    @classmethod
    def valid(cls, value):
        return validate_template(value)


def template_for(db, language, kind):
    row = db.get(MessageTemplate, (language, kind))
    return canonical_template(row.text) if row else default_template(language, kind)


def message(event, data, text=None):
    return (text if text is not None else default_template(data['language'], event.kind)).format_map(message_values(event, data))


def template_preview(language, kind, text):
    sample = {'username': 'sample-customer', 'profile': '20 Mbps', 'expiration': '2027-01-01 18:00:00',
              'reference': None if kind in EXPIRY_KINDS else 'SAMPLE-12345', 'card': '••••1234' if kind == 'card' else None,
              'extension': '7 days' if kind == 'extend' else None,
              'recharge_cost': '25000' if kind in METHODS else None,
              'service_price': '25000' if kind == 'credit' else None, 'currency': 'IQD'}
    if kind in EXPIRY_KINDS:
        sample['expiration'] = (now() + timedelta(hours=71 if kind == 'expiry_3days' else -1)).isoformat()
    return message(SimpleNamespace(kind=kind, created_at=now()),
                   {'language': language, 'timezone': 'Asia/Baghdad', 'receipt': sample}, text)


def template_response(db, language, kind):
    row = db.get(MessageTemplate, (language, kind))
    text = canonical_template(row.text) if row else default_template(language, kind)
    return {'text': text, 'customized': row is not None, 'placeholders': list(PLACEHOLDERS),
            'preview': template_preview(language, kind, text)}


@router.get('/templates/{language}/{kind}')
def read_template(language: TemplateLanguage, kind: TemplateKind, user=Depends(accounts.owner), db=Depends(get_db)):
    return template_response(db, language, kind)


@router.post('/templates/{language}/{kind}/preview')
def preview_template(language: TemplateLanguage, kind: TemplateKind, data: TemplateInput, user=Depends(accounts.owner)):
    return {'preview': template_preview(language, kind, data.text)}


@router.put('/templates/{language}/{kind}')
def save_template(language: TemplateLanguage, kind: TemplateKind, data: TemplateInput, user=Depends(accounts.owner), db=Depends(get_db)):
    with accounts.locked('recharge-settings'):
        selection = db.get(Settings, 1)
        with accounts.locked(selection.user_id if selection else user.id):
            row = db.get(MessageTemplate, (language, kind)) or MessageTemplate(language=language, kind=kind)
            row.text = data.text
            db.add(row)
            audit(db, user, 'telegram_recharge.template', language + ':' + kind)
            db.commit()
            return template_response(db, language, kind)


@router.delete('/templates/{language}/{kind}')
def reset_template(language: TemplateLanguage, kind: TemplateKind, user=Depends(accounts.owner), db=Depends(get_db)):
    with accounts.locked('recharge-settings'):
        selection = db.get(Settings, 1)
        with accounts.locked(selection.user_id if selection else user.id):
            row = db.get(MessageTemplate, (language, kind))
            if row:
                db.delete(row)
            audit(db, user, 'telegram_recharge.template.reset', language + ':' + kind)
            db.commit()
            return template_response(db, language, kind)


def test_message(db, record, language):
    selection = db.get(Settings, 1)
    data = {'language': language, 'timezone': selection.timezone if selection else 'Asia/Baghdad',
            'receipt': {'username': record.get('username'), 'profile': record.get('profile_name'),
                        'expiration': record.get('expiration'), 'reference': 'TEST'}}
    return message(SimpleNamespace(kind='test', created_at=now()), data, template_for(db, language, 'test'))


def cancel(event, detail):
    event.status, event.detail = 'cancelled', detail


def deliver(db, event):
    if event.status != 'pending':
        return
    selection = db.get(Settings, 1)
    sender, actor = db.get(User, event.user_id), db.get(User, event.actor_id) if event.actor_id else None
    if (not selection or not (expiry_enabled(db) if event.kind in EXPIRY_KINDS else selection.enabled)
            or (event.kind not in EXPIRY_KINDS and selection.version != event.version) or selection.user_id != event.user_id
            or not sender or not sender.active or not has_capability(sender, 'telegram_bot', db, write=True) or not customers.allowed(db, actor, True)):
        cancel(event, 'Notification settings or account access changed.')
        db.commit()
        return
    data = payload(event)
    if event.kind in EXPIRY_KINDS and (data.get('sender_id') != selection.sender_id or data['timezone'] != selection.timezone):
        cancel(event, 'The expiry sender or timezone changed.')
        db.commit()
        return
    sender_connection = db.get(SAS4UserConnection, sender.id)
    actor_connection = db.get(SAS4UserConnection, actor.id)
    if (not sender_connection or sender_connection.username != selection.sas4_username
            or not actor_connection or actor_connection.username != data.get('actor_connection')):
        cancel(event, 'SAS4 account connection changed.')
        db.commit()
        return
    try:
        with accounts.locked(sender.id):
            db.refresh(selection)
            if (not (expiry_enabled(db) if event.kind in EXPIRY_KINDS else selection.enabled)
                    or (event.kind not in EXPIRY_KINDS and selection.version != event.version) or selection.user_id != event.user_id
                    or event.kind in EXPIRY_KINDS and (data.get('sender_id') != selection.sender_id or data['timezone'] != selection.timezone)):
                cancel(event, 'Notification settings changed.')
                db.commit()
                return
            account = db.get(TelegramAccount, sender.id)
            state = accounts.read(account)
            if accounts.public(state)['stage'] != 'connected' or state['profile']['id'] != selection.sender_id:
                cancel(event, 'The selected Telegram account is disconnected or changed.')
                db.commit()
                return
            accounts.check_cooldown(account)
            event.attempts += 1
            # Validate both the recharge actor and selected sender still see the
            # same customer and phone. Never silently redirect a queued receipt.
            record = customers.record_for(db, actor, event.customer_id)
            owner_record = record if actor.id == sender.id else customers.record_for(db, sender, event.customer_id)
            receipt = data['receipt']
            if event.kind in EXPIRY_KINDS:
                expected = customers.expiry_time(receipt.get('expiration'), data['timezone'])
                actual = customers.expiry_time(record.get('expiration'), data['timezone'])
                if (not expected or not actual or expected != actual
                        or expiry_kind(actual) != event.kind or customers.sas4.flag(record.get('enabled')) is False):
                    cancel(event, 'The service expiry changed or this reminder is no longer due.')
                    db.commit()
                    return
                if not receipt.get('phone_hash'):
                    receipt['phone_hash'] = customers.phone_hash(record)
                    if not receipt['phone_hash']:
                        event.status, event.detail = 'skipped', 'No valid customer phone is saved for this expiry alert.'
                        db.commit()
                        return
                    event.encrypted_payload = cipher().encrypt(json.dumps(data).encode()).decode()
                    db.commit()
            if any(r.get('username') != receipt.get('username') or customers.phone_hash(r) != receipt.get('phone_hash')
                   for r in (record, owner_record)):
                cancel(event, 'Customer phone or identity changed after recharge.')
                db.commit()
                return
            phone = customers.normalized_phone(record.get('phone'))

            async def send(client):
                accounts.throttle('lookup:' + selection.sender_id, 3)
                try:
                    result = await client(functions.contacts.ResolvePhoneRequest(phone='+' + phone))
                except (errors.PhoneNotOccupiedError, errors.PhoneNumberUnoccupiedError):
                    result = None
                peer_id = getattr(getattr(result, 'peer', None), 'user_id', None)
                person = next((p for p in getattr(result, 'users', []) if p.id == peer_id
                    and not getattr(p, 'deleted', False) and not getattr(p, 'bot', False)
                    and not getattr(p, 'min', False) and getattr(p, 'access_hash', None) is not None), None)
                if not person:
                    event.status, event.detail = 'skipped', 'Telegram returned no accessible phone match. Privacy settings may prevent discovery.'
                    db.commit()
                    return
                accounts.throttle('recharge-send:' + selection.sender_id, 3)
                # Commit before sending. A crash/timeout is left unconfirmed and
                # never picked up for another send by the worker.
                data['language'] = selection.language
                event.encrypted_payload = cipher().encrypt(json.dumps(data).encode()).decode()
                event.status, event.detail = 'unconfirmed', 'Sending; Telegram confirmation is pending. Check the chat before any manual resend.'
                db.commit()
                try:
                    await client(functions.messages.SendMessageRequest(
                        peer=types.InputPeerUser(person.id, person.access_hash),
                        message=message(event, data, template_for(db, data['language'], event.kind)),
                        random_id=int(event.id[:15], 16), no_webpage=True))
                except (errors.UserPrivacyRestrictedError, errors.UserIsBlockedError, errors.YouBlockedUserError,
                        errors.ChatWriteForbiddenError, errors.UserNotMutualContactError, errors.PeerFloodError):
                    event.status, event.detail = 'failed', 'Telegram privacy, blocking or account restrictions prevented this notification.'
                    db.commit()
                    return
                event.status, event.sent_at, event.detail = 'sent', now(), 'Telegram accepted the notification.'
                audit(db, sender, 'telegram_recharge.sent', event.id)
                db.commit()
            accounts.perform(db, account, state, send, delivery=True)
    except Exception as exc:
        # Retry only failures BEFORE a send was attempted. Never recharge here.
        if event.status == 'pending':
            wait = 60
            if isinstance(exc, HTTPException) and exc.status_code in (409, 429, 503):
                try:
                    wait = max(5, int((exc.headers or {}).get('Retry-After', 30)))
                except (TypeError, ValueError):
                    pass
            elif event.attempts >= 3:
                event.status = 'failed'
            event.detail = 'Notification is waiting for Telegram or SAS4 access.'
            event.next_attempt = now() + timedelta(seconds=min(wait, 86400))
        elif event.status == 'unconfirmed':
            event.detail = 'Telegram did not confirm delivery. Check the customer chat; this message will not be retried automatically.'
        db.commit()


def recent(db, customer_id, record):
    rows = db.scalars(select(Event).where(Event.customer_id == customer_id).order_by(Event.created_at.desc()).limit(10)).all()
    return [{'kind': event.kind, 'status': event.status, 'detail': event.detail,
             'created_at': event.created_at, 'sent_at': event.sent_at}
            for event in rows if (data := payload(event))['receipt'].get('username') == record.get('username')
            and (data['receipt'].get('phone_hash') == customers.phone_hash(record)
                 or event.kind in EXPIRY_KINDS and not data['receipt'].get('phone_hash'))]


def tick(db):
    scan_expiry(db)
    event = db.scalar(select(Event).where(Event.status == 'pending', Event.next_attempt <= now()).order_by(Event.next_attempt).limit(1))
    if event:
        deliver(db, event)
    db.execute(delete(Event).where(Event.created_at < now() - timedelta(days=90), Event.status != 'pending')
               .execution_options(synchronize_session=False))
    db.commit()


def expiry_kind(expiry):
    remaining = expiry - now()
    if timedelta(days=2) < remaining <= timedelta(days=3):
        return 'expiry_3days'
    if -timedelta(days=1) < remaining <= timedelta(0):
        return 'expired'
    return None


def scan_expiry(db):
    schedule, selection = db.get(ExpirySchedule, 1), db.get(Settings, 1)
    if not schedule or not schedule.enabled or aware(schedule.next_check) > now():
        return
    try:
        if not selection:
            raise ValueError()
        sender = db.get(User, selection.user_id)
        connection = db.get(SAS4UserConnection, selection.user_id)
        state = accounts.read(db.get(TelegramAccount, selection.user_id))
        if (not sender or not sender.active or not has_capability(sender, 'telegram_bot', db, write=True) or not connection
                or connection.username != selection.sas4_username or accounts.public(state)['stage'] != 'connected'
                or state['profile']['id'] != selection.sender_id):
            raise ValueError()
        # A bounded page per minute, then an hourly pause after a complete pass.
        clients = customers.sas4.fetch_clients(connection, cipher().decrypt(connection.encrypted_password.encode()).decode(),
                                               page=schedule.page, count=25)
        if clients['page'] != schedule.page:
            raise ValueError()
        for record in clients['clients']:
            cid = record.get('id')
            expiry = customers.expiry_time(record.get('expiration'), selection.timezone)
            kind = expiry_kind(expiry) if expiry else None
            if (not kind or type(cid) is not int or cid < 1 or not record.get('username')
                    or record.get('enabled') is False):
                continue
            identity = f"expiry:{selection.user_id}:{cid}:{record['username']}:{kind}:{expiry.astimezone(timezone.utc).isoformat()}"
            event_id = hashlib.sha256(identity.encode()).hexdigest()
            if db.get(Event, event_id):
                continue
            data = {'receipt': {'username': record['username'], 'profile': record.get('profile'),
                                'expiration': str(record['expiration']), 'phone_hash': None},
                    'language': selection.language, 'timezone': selection.timezone,
                    'actor_connection': connection.username, 'sender_id': selection.sender_id}
            db.add(Event(id=event_id, user_id=sender.id, actor_id=sender.id, customer_id=cid,
                         version=selection.version, kind=kind,
                         encrypted_payload=cipher().encrypt(json.dumps(data).encode()).decode()))
        complete = schedule.page >= clients['last_page']
        schedule.page = 1 if complete else schedule.page + 1
        schedule.next_check = now() + timedelta(seconds=3600 if complete else 60)
        schedule.last_checked, schedule.last_error = now(), None
    except Exception:
        schedule.last_error = 'Expiry check unavailable. Check the selected owner Telegram and SAS4 accounts.'
        schedule.next_check = now() + timedelta(minutes=5)
    db.commit()
