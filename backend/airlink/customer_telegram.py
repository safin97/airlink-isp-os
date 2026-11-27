"""Opt-in customer notifications through one shared owner Telegram bot."""
import asyncio
import hashlib
import hmac
import json
import re
import secrets
from datetime import datetime, timedelta
from typing import Literal, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from types import SimpleNamespace
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select, delete, or_
from . import sas4, section_access, telegram
from .db import get_db, SessionLocal
from .models import (CustomerTelegramBot as Bot, CustomerTelegramLink as Link,
                     CustomerTelegramSender as Sender,
                     CustomerTelegramEvent as Event, TelegramSettings, SAS4UserConnection, User, now, uid, audit)
from .security import current_user, cipher, aware

router = APIRouter(prefix='/api/integrations/customer-telegram', tags=['Customer Telegram'])
FAILURE = 'Customer notification unavailable. Check Telegram, SAS4 access and internet connectivity.'
METHODS = {'card', 'credit', 'extend', 'fib', 'fastpay', 'expiry', 'linked'}


def normalized_phone(value):
    """International numbers; local Iraqi mobile notation is explicitly supported."""
    if not isinstance(value, str) or len(value) > 64:
        return None
    value = re.sub(r'[\s()\-]', '', value)
    value = ''.join(str(int(c)) if c.isdecimal() else c for c in value)
    if re.fullmatch(r'07[0-9]{9}', value):
        value = '964' + value[1:]
    elif re.fullmatch(r'7[0-9]{9}', value):
        value = '964' + value
    elif value.startswith('00'):
        value = value[2:]
    elif value.startswith('+'):
        value = value[1:]
    return value if re.fullmatch(r'[1-9][0-9]{7,14}', value) else None


def phone_hash(record):
    from .config import settings
    phone = normalized_phone(record.get('phone'))
    return hmac.new(settings.encryption_key.encode(), ('customer-telegram-phone:' + phone).encode(),
                    hashlib.sha256).hexdigest() if phone else None


def verified_phone(link, record):
    expected = phone_hash(record)
    return bool(link and link.phone_verified_at and expected and link.phone_hash
                and hmac.compare_digest(link.phone_hash, expected))


def notification_language(db, fallback='en'):
    from .recharge_telegram import language_for
    return language_for(db, fallback)


def allowed(db, user, edit=False):
    return bool(user and user.active and (user.role in ('owner', 'manager') or section_access.role_policy(user, db) is not None)
        and (user.role == 'owner' or 'isp_card' in (
        section_access.editable(user, db) if edit else section_access.effective(user, db))))


def access(user=Depends(current_user), db=Depends(get_db)):
    if not allowed(db, user):
        raise HTTPException(403, 'ISP card access is required')
    return user


def editor(user=Depends(access), db=Depends(get_db)):
    if not allowed(db, user, True):
        raise HTTPException(403, 'ISP card edit permission is required')
    return user


def configured(db, user_id=None):
    """Resolve the shared owner sender. Never fall back to a manager's token."""
    selection = db.get(Sender, 1)
    if selection:
        bot = db.get(Bot, selection.user_id)
    else:
        # Preserve a single pre-existing owner bot during upgrade. Multiple owners
        # must explicitly save their choice instead of choosing an arbitrary sender.
        owners = db.scalars(select(Bot).join(User, User.id == Bot.user_id)
            .where(User.role == 'owner', User.active.is_(True)).limit(2)).all()
        bot = owners[0] if len(owners) == 1 else None
    owner = db.get(User, bot.user_id) if bot else None
    connection = db.get(SAS4UserConnection, bot.user_id) if bot else None
    if bot and owner and owner.active and section_access.has_capability(owner, 'telegram_bot', db, write=True) and connection and bot.sas4_username == connection.username:
        return bot
    return None


def record_for(db, user, customer_id):
    if customer_id < 1:
        raise HTTPException(422, 'Invalid customer ID')
    connection, password = sas4.local_user_connection(db, user)
    try:
        with sas4.sas4_session(connection, password) as (client, headers):
            return sas4.raw_user(client, headers, customer_id)
    except Exception:
        # Never surface provider bodies or credentials in notification errors.
        raise HTTPException(502, 'Customer access could not be verified in SAS4.') from None


def api(bot, method, body):
    import urllib.request
    try:
        token = cipher().decrypt(bot.encrypted_token.encode()).decode()
        request = urllib.request.Request('https://api.telegram.org/bot' + token + '/' + method,
            data=json.dumps(body).encode(), headers={'Content-Type': 'application/json'}, method='POST')
        with urllib.request.build_opener(telegram.NoRedirect()).open(request, timeout=8) as response:
            payload = json.loads(response.read(2 * 1024 * 1024))
        if not isinstance(payload, dict) or payload.get('ok') is not True:
            raise ValueError()
        return payload['result']
    except Exception:
        raise RuntimeError(FAILURE) from None


class BotInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    bot_token: Optional[str] = Field(default=None, pattern=r'^[0-9]+:[A-Za-z0-9_-]+$', max_length=256)
    enabled: bool = True
    timezone: str = Field(default='Asia/Baghdad', max_length=64)

    @field_validator('timezone')
    @classmethod
    def valid_timezone(cls, value):
        try:
            ZoneInfo(value)
        except (ZoneInfoNotFoundError, ValueError):
            raise ValueError('Enter an IANA timezone, for example Asia/Baghdad')
        return value


class LinkInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    language: Literal['en', 'ku', 'ar'] = 'en'


def public_bot(bot):
    return {'configured': bot is not None, 'enabled': bool(bot and bot.enabled),
            'username': bot.username if bot else None, 'timezone': bot.timezone if bot else 'Asia/Baghdad',
            'last_error': bot.last_error if bot else None}


@router.get('')
def status(user=Depends(access), db=Depends(get_db)):
    return {**public_bot(configured(db)), 'can_manage': section_access.has_capability(user, 'telegram_bot', db, write=True), 'sender': 'owner'}


@router.put('')
def save_bot(data: BotInput, user=Depends(editor), db=Depends(get_db)):
    section_access.require_any(user, ('telegram_bot',), db, write=True)
    sender = configured(db)
    if sender and sender.user_id != user.id and not data.bot_token:
        raise HTTPException(409, 'Another owner configured the shared sender. Enter your bot token to replace it.')
    bot = db.get(Bot, user.id)
    if bot and not data.enabled and not data.bot_token:
        bot.enabled, bot.timezone = False, data.timezone
        db.execute(delete(Event).where(Event.user_id == user.id, Event.status == 'pending'))
        audit(db, user, 'customer_telegram.disable', user.id)
        db.commit()
        return public_bot(bot)
    connection, _ = sas4.local_user_connection(db, user)
    if not data.bot_token and not bot:
        raise HTTPException(422, 'Enter a dedicated customer bot token')
    encrypted = cipher().encrypt(data.bot_token.encode()).decode() if data.bot_token else bot.encrypted_token
    candidate = SimpleNamespace(encrypted_token=encrypted)
    try:
        identity = api(candidate, 'getMe', {})
        webhook = api(candidate, 'getWebhookInfo', {})
    except RuntimeError:
        raise HTTPException(502, FAILURE) from None
    if not isinstance(identity, dict) or identity.get('is_bot') is not True or not identity.get('username') or type(identity.get('id')) is not int:
        raise HTTPException(422, 'Telegram did not identify a valid bot')
    bot_id = str(identity['id'])
    if not isinstance(webhook, dict) or webhook.get('url'):
        raise HTTPException(409, 'This bot has a webhook. Use a dedicated customer notification bot.')
    if db.scalar(select(Bot).where(Bot.bot_id == bot_id, Bot.user_id != user.id)):
        raise HTTPException(409, 'This customer bot belongs to another account')
    for alert in db.scalars(select(TelegramSettings)):
        if cipher().decrypt(alert.encrypted_token.encode()).decode().split(':', 1)[0] == bot_id:
            raise HTTPException(409, 'Use a separate bot from manager device alerts')
    changed = bot and (bot.bot_id != bot_id or bot.sas4_username != connection.username)
    if changed:
        db.execute(delete(Event).where(Event.user_id == user.id))
        db.execute(delete(Link).where(Link.user_id == user.id))
    if bot is None:
        bot = Bot(user_id=user.id, offset=0)
        db.add(bot)
    if changed:
        bot.offset = 0
    bot.bot_id, bot.username, bot.encrypted_token = bot_id, identity['username'], encrypted
    bot.sas4_username, bot.enabled, bot.timezone = connection.username, data.enabled, data.timezone
    bot.last_error, bot.poll_at = None, now()
    db.flush()
    selection = db.get(Sender, 1)
    if selection is None:
        selection = Sender(id=1, user_id=user.id)
        db.add(selection)
    elif selection.user_id != user.id:
        # No queued confirmations from a retired sender may cross to its replacement.
        db.execute(delete(Event).where(Event.status == 'pending'))
        selection.user_id = user.id
    if not data.enabled:
        db.execute(delete(Event).where(Event.user_id == user.id, Event.status == 'pending'))
    audit(db, user, 'customer_telegram.configure', user.id)
    db.commit()
    return public_bot(bot)


@router.get('/users/{customer_id}')
def customer_status(customer_id: int, user=Depends(access), db=Depends(get_db)):
    from . import recharge_telegram
    record = record_for(db, user, customer_id)
    bot = configured(db)
    link = db.get(Link, (bot.user_id, customer_id)) if bot else None
    valid = bool(bot and link and link.customer_username == record.get('username'))
    verified = bool(valid and verified_phone(link, record))
    pending = bool(valid and (link.token_hash or link.pending_chat_id) and link.token_expires and aware(link.token_expires) > now())
    selection = db.get(recharge_telegram.Settings, 1)
    return {'account_recharges': recharge_telegram.recent(db, customer_id, record),
            'phone_recharges_enabled': bool(selection and selection.enabled),
            'language_managed': selection is not None,
            'linked': bool(verified and link.chat_id), 'language': notification_language(db, link.language if valid else 'en'),
            'telegram_linked': bool(valid and link.chat_id),
            'test_ready': bool(valid and link.chat_id and bot.enabled and (not link.phone_verified_at or verified)),
            'phone_verified': verified, 'phone_available': phone_hash(record) is not None,
            'awaiting_phone': bool(pending and link.pending_chat_id),
            'pending_link': pending,
            'last_sent_at': link.last_sent_at if valid else None, 'last_error': link.last_error if valid else None,
            'recent': [{'kind': e.kind, 'status': e.status, 'created_at': e.created_at, 'sent_at': e.sent_at}
                       for e in db.scalars(select(Event).where(Event.user_id == bot.user_id, Event.customer_id == customer_id,
                           Event.version == link.version).order_by(Event.created_at.desc()).limit(10))] if valid else []}


@router.post('/users/{customer_id}/link')
def create_link(customer_id: int, data: LinkInput, user=Depends(editor), db=Depends(get_db)):
    record = record_for(db, user, customer_id)
    bot = configured(db, user.id)
    if not bot or not bot.enabled:
        raise HTTPException(409, 'Ask the owner to configure and enable the customer Telegram bot')
    expected_phone = phone_hash(record)
    if not expected_phone:
        raise HTTPException(409, 'Save a valid customer phone number in ISP card first. Use international format, such as +964..., or an Iraqi 07... mobile number.')
    if user.id != bot.user_id:
        owner_record = record_for(db, db.get(User, bot.user_id), customer_id)
        if record.get('username') != owner_record.get('username') or phone_hash(owner_record) != expected_phone:
            raise HTTPException(409, 'The customer identity or phone does not match the owner SAS4 account')
    link = db.get(Link, (bot.user_id, customer_id))
    if link is None:
        link = Link(user_id=bot.user_id, customer_id=customer_id)
        db.add(link)
    if link.chat_id and verified_phone(link, record):
        raise HTTPException(409, 'Unlink the current recipient before creating a new link')
    token = secrets.token_urlsafe(32)
    link.version, link.customer_username, link.language = uid(), str(record['username']), notification_language(db, data.language)
    link.token_hash, link.token_expires = hashlib.sha256(token.encode()).hexdigest(), now() + timedelta(hours=24)
    link.next_check, link.last_error, link.last_sent_at = now(), None, None
    link.chat_id, link.pending_chat_id, link.phone_verified_at, link.phone_hash = None, None, None, expected_phone
    audit(db, user, 'customer_telegram.link.create', str(customer_id))
    db.commit()
    return {'url': f'https://t.me/{bot.username}?start={token}', 'expires_at': link.token_expires}


@router.put('/users/{customer_id}/language')
def language(customer_id: int, data: LinkInput, user=Depends(editor), db=Depends(get_db)):
    record = record_for(db, user, customer_id)
    bot = configured(db)
    link = db.get(Link, (bot.user_id, customer_id)) if bot else None
    if not link or link.customer_username != record.get('username'):
        raise HTTPException(404, 'Customer link not found')
    effective = notification_language(db, data.language)
    if effective != data.language:
        raise HTTPException(409, 'Customer language is managed in My account → Telegram account lookup.')
    link.language = effective
    db.commit()
    return {'language': link.language}


@router.delete('/users/{customer_id}')
def unlink(customer_id: int, user=Depends(editor), db=Depends(get_db)):
    record = record_for(db, user, customer_id)
    bot = configured(db)
    link = db.get(Link, (bot.user_id, customer_id)) if bot else None
    if link and link.customer_username != record.get('username'):
        raise HTTPException(404, 'Customer link not found')
    if bot:
        db.execute(delete(Event).where(Event.user_id == bot.user_id, Event.customer_id == customer_id))
        db.execute(delete(Link).where(Link.user_id == bot.user_id, Link.customer_id == customer_id))
    audit(db, user, 'customer_telegram.unlink', str(customer_id))
    db.commit()
    return {'linked': False}


@router.post('/users/{customer_id}/test')
def send_test(customer_id: int, user=Depends(editor), db=Depends(get_db)):
    record = record_for(db, user, customer_id)
    bot = configured(db)
    link = db.get(Link, (bot.user_id, customer_id)) if bot else None
    if not bot or not bot.enabled:
        raise HTTPException(409, 'The owner must enable the customer Telegram bot first')
    if not link or not link.chat_id or link.customer_username != record.get('username'):
        raise HTTPException(409, 'Link this customer to the owner bot before sending a test')
    if link.phone_verified_at and not verified_phone(link, record):
        raise HTTPException(409, 'The customer phone changed. Verify the new phone before sending a test.')
    from .api import cache
    from redis.exceptions import RedisError
    try:
        if not cache.set(f'customer-telegram:test:{bot.user_id}:{customer_id}', 'sending', nx=True, ex=30):
            raise HTTPException(429, 'Wait 30 seconds before sending another test to this customer')
    except RedisError:
        raise HTTPException(503, 'Test delivery protection is unavailable. Try again later.') from None
    # Explicit tests are sent once, immediately. They are never picked up by the
    # background queue or automatically retried after an ambiguous timeout.
    event = Event(id=hashlib.sha256(uid().encode()).hexdigest(), user_id=bot.user_id,
                  customer_id=customer_id, version=link.version, kind='test', status='unconfirmed')
    db.add(event)
    audit(db, user, 'customer_telegram.test', str(customer_id))
    db.commit()
    deliver(db, event, retry=False)
    if event.status == 'cancelled':
        raise HTTPException(409, 'Customer link or owner access changed. Refresh before sending a test.')
    if event.status != 'sent':
        raise HTTPException(502, 'Telegram did not confirm the test. Check delivery status and the customer chat before trying again.')
    return {'sent': True, 'sent_at': event.sent_at}


def enqueue(db, user_id, customer_id, kind, key, expiration=None):
    if kind not in METHODS or not allowed(db, db.get(User, user_id), True):
        return
    bot = configured(db)
    link = db.get(Link, (bot.user_id, customer_id)) if bot else None
    if not bot or not bot.enabled or not link or not link.chat_id or not link.phone_verified_at:
        return
    event_id = hashlib.sha256(f'{user_id}:{customer_id}:{link.version}:{kind}:{key}'.encode()).hexdigest()
    if db.get(Event, event_id) is None:
        db.add(Event(id=event_id, user_id=bot.user_id, customer_id=customer_id, version=link.version,
                     kind=kind, expiration=expiration))


def activation(db, user, customer_id, method, transaction_id, receipt=None):
    # A notification problem must never turn a confirmed recharge into a retry.
    from . import twilio_whatsapp
    twilio_whatsapp.activation(db, user, customer_id, method, transaction_id, receipt)
    try:
        with db.begin_nested():
            from . import recharge_telegram
            if not recharge_telegram.enqueue(db, user, customer_id, method, transaction_id, receipt):
                enqueue(db, user.id, customer_id, method, transaction_id)
            db.flush()
    except Exception:
        audit(db, user, 'customer_telegram.queue_failed', str(customer_id))


def poll_bot(db, bot):
    selected = configured(db)
    if not selected or selected.user_id != bot.user_id:
        return
    updates = api(bot, 'getUpdates', {'offset': bot.offset, 'limit': 3, 'timeout': 0, 'allowed_updates': ['message']})
    if not isinstance(updates, list):
        raise RuntimeError(FAILURE)
    for update in updates:
        if not isinstance(update, dict) or type(update.get('update_id')) is not int:
            continue
        if update['update_id'] < bot.offset:
            continue
        message = update.get('message') or {}
        chat, sender = message.get('chat') or {}, message.get('from') or {}
        text = message.get('text', '')
        if (chat.get('type') == 'private' and type(chat.get('id')) is int and chat['id'] > 0
                and sender.get('id') == chat['id'] and sender.get('is_bot') is False and isinstance(text, str)):
            if text.strip() == '/stop':
                for link in db.scalars(select(Link).where(Link.user_id == bot.user_id,
                        or_(Link.chat_id == str(chat['id']), Link.pending_chat_id == str(chat['id'])))):
                    link.chat_id, link.token_hash, link.version = None, None, uid()
                    link.pending_chat_id, link.phone_hash, link.phone_verified_at = None, None, None
            elif re.fullmatch(r'/start [A-Za-z0-9_-]{43}', text.strip()):
                digest = hashlib.sha256(text.strip().split(' ', 1)[1].encode()).hexdigest()
                link = db.scalar(select(Link).where(Link.user_id == bot.user_id, Link.token_hash == digest))
                if link and not link.phone_verified_at and aware(link.token_expires) > now():
                    record = record_for(db, db.get(User, bot.user_id), link.customer_id)
                    expected = phone_hash(record)
                    if record.get('username') == link.customer_username and expected and (not link.phone_hash or link.phone_hash == expected):
                        ask_phone(bot, link, str(chat['id']), notification_language(db, link.language))
                        for previous in db.scalars(select(Link).where(Link.user_id == bot.user_id,
                                Link.pending_chat_id == str(chat['id']), Link.customer_id != link.customer_id)):
                            previous.pending_chat_id = None
                        link.pending_chat_id, link.token_hash, link.phone_hash = str(chat['id']), None, expected
                        link.chat_id, link.last_error = None, None
                    else:
                        link.last_error = 'Customer phone or identity changed. Save the correct ISP card phone and create a new link.'
            elif isinstance(message.get('contact'), dict):
                contact = message['contact']
                link = db.scalar(select(Link).where(Link.user_id == bot.user_id,
                    Link.pending_chat_id == str(chat['id']), Link.token_expires > now()).limit(1))
                if link:
                    record = record_for(db, db.get(User, bot.user_id), link.customer_id)
                    supplied = phone_hash({'phone': contact.get('phone_number')})
                    if (type(contact.get('user_id')) is int and contact['user_id'] == sender['id']
                            and supplied and supplied == link.phone_hash == phone_hash(record)
                            and record.get('username') == link.customer_username):
                        link.chat_id, link.pending_chat_id, link.phone_verified_at = str(chat['id']), None, now()
                        link.last_error, link.next_check = None, now()
                        enqueue(db, bot.user_id, link.customer_id, 'linked', link.version)
                    else:
                        link.last_error = 'Shared Telegram phone did not match the ISP card phone. Use your own contact and check the customer phone.'
                        api(bot, 'sendMessage', {'chat_id': str(chat['id']), 'text': LABELS[notification_language(db, link.language)]['phone_mismatch']})
            elif text.strip() == '/start':
                link = db.scalar(select(Link).where(Link.user_id == bot.user_id,
                    Link.pending_chat_id == str(chat['id']), Link.token_expires > now()).limit(1))
                if link:
                    ask_phone(bot, link, str(chat['id']), notification_language(db, link.language))
        bot.offset = update['update_id'] + 1
        db.commit()  # Commit binding before acknowledging the update on Telegram.
    bot.last_error = None


def ask_phone(bot, link, chat_id, language=None):
    labels = LABELS[language or link.language]
    api(bot, 'sendMessage', {'chat_id': chat_id, 'text': labels['phone_request'],
        'reply_markup': {'keyboard': [[{'text': labels['phone_button'], 'request_contact': True}]],
                         'resize_keyboard': True, 'one_time_keyboard': True}})


def expiry_time(value, zone):
    try:
        result = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return result.replace(tzinfo=ZoneInfo(zone)) if result.tzinfo is None else result
    except (ValueError, TypeError, ZoneInfoNotFoundError):
        return None


def check_expiry(db, bot, link, record):
    from .recharge_telegram import expiry_enabled
    if expiry_enabled(db):
        return  # The selected account route owns reminders; avoid duplicate bot alerts.
    expiry = expiry_time(record.get('expiration'), bot.timezone)
    # One reminder in the third day before expiry, never a misleading late reminder.
    if verified_phone(link, record) and record.get('username') == link.customer_username and expiry and timedelta(days=2) < expiry - now() <= timedelta(days=3):
        enqueue(db, bot.user_id, link.customer_id, 'expiry', expiry.isoformat(), str(record['expiration']))


LABELS = {
    'en': {'card': 'Service activated by card PIN.', 'credit': 'Service activated by account balance.',
           'phone_request': 'To receive ISP notifications, tap Share my phone number below. Your Telegram phone must match the phone saved in your ISP account.',
           'phone_button': 'Share my phone number',
           'phone_mismatch': 'Your own Telegram phone must match your ISP account. Use the Share my phone number button or contact your ISP to correct the saved number.',
           'test': 'Test notification from your ISP. Your Telegram notifications are connected.',
           'extend': 'Service extended.', 'fib': 'FIB payment verified. Service activated.',
           'fastpay': 'FastPay payment verified. Service activated.', 'expiry': 'Your service expires in 3 days.',
           'linked': 'Telegram notifications connected.', 'user': 'Customer', 'expiry_label': 'Current expiry',
           'stop': 'Send /stop to unsubscribe.'},
    'ar': {'card': 'تم تفعيل الخدمة ببطاقة التعبئة.', 'credit': 'تم تفعيل الخدمة من رصيد الحساب.',
           'phone_request': 'لتلقي الإشعارات، اضغط مشاركة رقم هاتفي. يجب أن يطابق رقم تيليجرام الرقم المسجل في حساب الإنترنت.',
           'phone_button': 'مشاركة رقم هاتفي',
           'phone_mismatch': 'يجب أن يطابق رقم تيليجرام الخاص بك رقم حساب الإنترنت. شارك رقمك باستخدام الزر أو اتصل بمزود الخدمة لتصحيح الرقم.',
           'test': 'إشعار تجريبي من مزود الإنترنت. إشعارات تيليجرام متصلة.',
           'extend': 'تم تمديد الخدمة.', 'fib': 'تم تأكيد دفع FIB وتفعيل الخدمة.',
           'fastpay': 'تم تأكيد دفع FastPay وتفعيل الخدمة.', 'expiry': 'تنتهي خدمتك خلال 3 أيام.',
           'linked': 'تم ربط إشعارات تيليجرام.', 'user': 'المشترك', 'expiry_label': 'انتهاء الخدمة الحالي',
           'stop': 'أرسل /stop لإلغاء الاشتراك.'},
    'ku': {'card': 'خزمەتگوزاری ب کارتی هاتە چالاککرن.', 'credit': 'خزمەتگوزاری ژ بالانسا هەژمارێ هاتە چالاککرن.',
           'phone_request': 'بۆ وەرگرتنا ئاگەهداریان، ژمارا تەلەفۆنا خۆ پشکدار بکە. ژمارا تێلێگرامێ دڤێت وەک ژمارا هەژمارا ئینتەرنێتێ بیت.',
           'phone_button': 'پشکدارکرنا ژمارا تەلەفۆنا من',
           'phone_mismatch': 'ژمارا تێلێگرامێ دڤێت وەک ژمارا هەژمارا ئینتەرنێتێ بیت. ژمارا خۆ پشکدار بکە یان پەیوەندیێ ب دابینکەرێ خۆ بکە.',
           'test': 'ئاگەهداریا تاقیکرنێ ژ دابینکەرێ ئینتەرنێتێ. ئاگەهداریێن تێلێگرامێ هاتنە گرێدان.',
           'extend': 'دەمێ خزمەتگوزاریێ هاتە درێژکرن.', 'fib': 'پارەدانا FIB هاتە پشتڕاستکرن و خزمەتگوزاری چالاک بوو.',
           'fastpay': 'پارەدانا FastPay هاتە پشتڕاستکرن و خزمەتگوزاری چالاک بوو.',
           'expiry': 'خزمەتگوزاریا تە پشتی 3 ڕۆژان ب دوماهی دهێت.', 'linked': 'ئاگەهداریێن تێلێگرامێ هاتنە گرێدان.',
           'user': 'بکارهێنەر', 'expiry_label': 'دەمێ دوماهیێ یێ نوکە', 'stop': 'بۆ راوەستاندنێ /stop بنێرە.'},
}


def deliver(db, event, retry=True):
    from .recharge_telegram import expiry_enabled
    if event.kind == 'expiry' and expiry_enabled(db):
        event.status = 'cancelled'
        db.commit()
        return
    bot, link, user = configured(db, event.user_id), db.get(Link, (event.user_id, event.customer_id)), db.get(User, event.user_id)
    # Manual tests may use a previously consented Telegram chat without the later
    # phone-verification requirement. Automatic messages still require verification.
    phone_required = event.kind != 'test' or retry
    if not bot or bot.user_id != event.user_id or not bot.enabled or not allowed(db, user, True) or not link or not link.chat_id or (phone_required and not link.phone_verified_at) or link.version != event.version:
        event.status = 'cancelled'
        db.commit()
        return
    event.attempts += 1
    try:
        record = record_for(db, user, link.customer_id)
        if record.get('username') != link.customer_username or ((phone_required or link.phone_verified_at) and not verified_phone(link, record)):
            event.status = 'cancelled'
            link.last_error = 'Customer phone or identity changed. Verify the customer phone again before sending notifications.'
        elif event.kind == 'expiry' and (str(record.get('expiration')) != event.expiration or
                not expiry_time(event.expiration, bot.timezone) or
                not timedelta(days=2) < expiry_time(event.expiration, bot.timezone) - now() <= timedelta(days=3)):
            event.status = 'cancelled'
        else:
            labels = LABELS[notification_language(db, link.language)]
            message = f"AirLink\n{labels[event.kind]}\n{labels['user']}: {link.customer_username}"
            expiry = expiry_time(record.get('expiration'), bot.timezone)
            if expiry:
                formatted = expiry.astimezone(ZoneInfo(bot.timezone)).strftime('%Y-%m-%d %H:%M')
                message += f"\n{labels['expiry_label']}: {formatted}"
            message += '\n' + labels['stop']
            body = {'chat_id': link.chat_id, 'text': message[:4000]}
            if event.kind == 'linked':
                body['reply_markup'] = {'remove_keyboard': True}
            api(bot, 'sendMessage', body)
            event.status, event.sent_at = 'sent', now()
            link.last_error, link.last_sent_at = None, event.sent_at
    except Exception:
        link.last_error = FAILURE
        event.status = 'failed' if not retry or event.attempts >= 5 else 'pending'
        event.next_attempt = now() + timedelta(seconds=min(900, 30 * 2 ** event.attempts))
    db.commit()


def tick():
    from .api import cache
    # One bounded worker across API processes. No remote activation is performed here.
    lock = cache.lock('customer-telegram:worker', timeout=600, blocking=False)
    if not lock.acquire(blocking=False):
        return
    try:
        with SessionLocal() as db:
            from . import recharge_telegram
            recharge_telegram.tick(db)
            bot = configured(db)
            if bot and bot.enabled and aware(bot.poll_at) <= now():
                bot.poll_at = now() + timedelta(seconds=5)
                if configured(db, bot.user_id) and allowed(db, db.get(User, bot.user_id), True):
                    try:
                        poll_bot(db, bot)
                    except Exception:
                        bot.last_error, bot.poll_at = FAILURE, now() + timedelta(seconds=60)
                db.commit()
            sender_id = bot.user_id if bot and bot.enabled else None
            for link in db.scalars(select(Link).where(Link.user_id == sender_id, Link.chat_id.is_not(None), Link.next_check <= now()).order_by(Link.next_check).limit(2)).all():
                link.next_check = now() + timedelta(hours=1)
                bot, user = configured(db, link.user_id), db.get(User, link.user_id)
                if bot and bot.enabled and allowed(db, user, True):
                    try:
                        check_expiry(db, bot, link, record_for(db, user, link.customer_id))
                    except Exception:
                        link.last_error, link.next_check = FAILURE, now() + timedelta(minutes=5)
                db.commit()
            event = db.scalar(select(Event).where(Event.status == 'pending', Event.next_attempt <= now()).order_by(Event.next_attempt).limit(1))
            if event:
                deliver(db, event)
            db.execute(delete(Event).where(Event.created_at < now() - timedelta(days=90), Event.status != 'pending')
                       .execution_options(synchronize_session=False))
            db.commit()
    finally:
        if lock.owned():
            lock.release()


async def worker():
    while True:
        try:
            await asyncio.to_thread(tick)
        except Exception:
            pass  # Retry safely; never log tokens or customer message bodies.
        await asyncio.sleep(5)
