"""Account-scoped Telegram delivery. Tokens never leave the server API."""
from typing import Literal, Optional
import json
import hashlib
import re
import urllib.request
from datetime import timedelta
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, ConfigDict, field_validator
from sqlalchemy import select, delete
from .db import get_db
from .models import TelegramSettings, TelegramNotification, User, Device, Tower, TelegramMessageTemplates, now, audit
from .security import current_user, cipher
from . import section_access

router = APIRouter(prefix='/api/integrations/telegram', tags=['Telegram'])

def account(user_id: Optional[str] = None, user=Depends(current_user), db=Depends(get_db)):
    section_access.require_any(user, ('telegram_notifications',), db)
    if user.role != 'owner' and user_id and user_id != user.id:
        raise HTTPException(403, 'You can manage only your own Telegram notifications')
    target = db.get(User, user_id) if user_id else user
    if not target or target.role not in ('owner', 'manager'):
        raise HTTPException(404, 'Owner or manager account not found')
    return target


def settings_for(db, user_id):
    return db.scalar(select(TelegramSettings).where(TelegramSettings.user_id == user_id))


def authorized(db, user, device_id):
    if not user or not user.active or user.role not in ('owner', 'manager'):
        return False
    if not set(section_access.effective(user, db)).intersection(('dashboard', 'noc', 'alerts')):
        return False
    from .api import devices_query
    return db.scalar(devices_query(db, user).where(Device.id == device_id)) is not None


class SettingsInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    enabled: bool = False
    chat_id: str = Field(pattern=r'^(-?[0-9]+|@[A-Za-z0-9_]{5,})$', max_length=128)
    bot_token: Optional[str] = Field(default=None, pattern=r'^[0-9]+:[A-Za-z0-9_-]+$', max_length=256)


def public(row):
    return {'enabled': bool(row and row.enabled), 'chat_id': row.chat_id if row else '',
            'has_token': bool(row), 'last_error': row.last_error if row else None,
            'last_sent_at': row.last_sent_at if row else None}

@router.get('/accounts/{user_id}')
@router.get('')
def status(user=Depends(account), db=Depends(get_db)):
    return public(settings_for(db, user.id))

@router.put('/accounts/{user_id}')
@router.put('')
def save(data: SettingsInput, user=Depends(account), db=Depends(get_db), actor=Depends(current_user)):
    if data.bot_token:
        from .models import CustomerTelegramBot
        if db.scalar(select(CustomerTelegramBot).where(CustomerTelegramBot.bot_id == data.bot_token.split(':', 1)[0])):
            raise HTTPException(409, 'Use a separate bot from customer notifications')
    row = settings_for(db, user.id)
    if row is None:
        if not data.bot_token:
            raise HTTPException(422, 'A bot token is required')
        row = TelegramSettings(user_id=user.id)
        db.add(row)
    if data.bot_token:
        row.encrypted_token = cipher().encrypt(data.bot_token.encode()).decode()
    row.chat_id, row.enabled, row.last_error = data.chat_id, data.enabled, None
    # Never deliver queued events to a newly selected destination.
    db.execute(delete(TelegramNotification).where(TelegramNotification.sent_at.is_(None), TelegramNotification.user_id == user.id))
    audit(db, actor, 'telegram.configure', user.id)
    db.commit()
    return public(row)

DEFAULT_MESSAGE = 'AirLink — {status}\nDevice: {device_name}\nTower: {tower_name}\nIP: {ip_address}\nTime: {time}'
MESSAGE_LANGUAGES = {
    'en': {'label': 'English', 'rtl': False, 'default_message': DEFAULT_MESSAGE,
           'down_status': 'DOWN / TIMEOUT', 'recovery_status': 'RECOVERED',
           'test_message': 'AirLink: Telegram notifications are connected.'},
    'ku': {'label': 'کوردی (بادینی)', 'rtl': True,
           'default_message': 'AirLink — {status}\nئامێر: {device_name}\nتاوەر: {tower_name}\nIP: {ip_address}\nدەم: {time}',
           'down_status': 'دەرەڤەی هێڵێ / دەم ب دوماهی هات', 'recovery_status': 'دووبارە سەرهێڵ',
           'test_message': 'AirLink: ئاگەهداریێن تێلێگرامێ هاتنە گرێدان.'},
    'ar': {'label': 'العربية', 'rtl': True,
           'default_message': 'AirLink — {status}\nالجهاز: {device_name}\nالبرج: {tower_name}\nIP: {ip_address}\nالوقت: {time}',
           'down_status': 'غير متصل / انتهت مهلة الاتصال', 'recovery_status': 'تمت استعادة الاتصال',
           'test_message': 'AirLink: تم توصيل إشعارات تيليجرام.'},
}
MESSAGE_FIELDS = ('status', 'device_name', 'ip_address', 'tower_name', 'time')
TOKEN_PATTERN = re.compile(r'\{([^{}]*)\}')


class MessageInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    language: Optional[Literal['en', 'ku', 'ar']] = None
    down_message: str = Field(min_length=1, max_length=1000)
    recovery_message: str = Field(min_length=1, max_length=1000)

    @field_validator('down_message', 'recovery_message')
    @classmethod
    def validate_message(cls, value):
        if not value.strip():
            raise ValueError('Enter a message')
        unknown = set(TOKEN_PATTERN.findall(value)) - set(MESSAGE_FIELDS)
        if unknown:
            raise ValueError('Supported placeholders: ' + ', '.join('{' + key + '}' for key in MESSAGE_FIELDS))
        return value


def message_settings(db, user_id):
    row = db.get(TelegramMessageTemplates, user_id)
    language = row.language if row else 'en'
    default_message = MESSAGE_LANGUAGES[language]['default_message']
    return {'down_message': row.down_message if row else default_message,
            'recovery_message': row.recovery_message if row else default_message,
            'language': language, 'languages': MESSAGE_LANGUAGES,
            'default_message': default_message, 'placeholders': list(MESSAGE_FIELDS)}


@router.get('/accounts/{user_id}/messages')
@router.get('/messages')
def messages(user=Depends(account), db=Depends(get_db)):
    return message_settings(db, user.id)


@router.put('/accounts/{user_id}/messages')
@router.put('/messages')
def save_messages(data: MessageInput, user=Depends(account), db=Depends(get_db), actor=Depends(current_user)):
    row = db.get(TelegramMessageTemplates, user.id)
    if row is None:
        row = TelegramMessageTemplates(user_id=user.id)
        db.add(row)
    row.down_message, row.recovery_message = data.down_message, data.recovery_message
    if data.language is not None:
        row.language = data.language
    audit(db, actor, 'telegram.messages.configure', user.id)
    db.commit()
    return message_settings(db, user.id)


def render_message(template, values):
    # Single-pass substitution: device names cannot introduce new placeholders.
    return TOKEN_PATTERN.sub(lambda match: str(values.get(match.group(1), match.group(0))), template)[:4000]


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def send(row, message):
    try:
        token = cipher().decrypt(row.encrypted_token.encode()).decode()
        request = urllib.request.Request('https://api.telegram.org/bot' + token + '/sendMessage',
            data=json.dumps({'chat_id': row.chat_id, 'text': message[:4000]}).encode(),
            headers={'Content-Type': 'application/json'}, method='POST')
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=8) as response:
            result = json.loads(response.read(65536))
        if not isinstance(result, dict) or result.get('ok') is not True:
            raise ValueError('Rejected')
    except Exception:
        # Network exceptions can contain the secret URL; never expose or log them.
        raise RuntimeError('Telegram delivery failed. Check bot token, chat ID, bot access and internet connection.') from None

@router.post('/accounts/{user_id}/test')
@router.post('/test')
def test_message(user=Depends(account), db=Depends(get_db), actor=Depends(current_user)):
    row = settings_for(db, user.id)
    if row is None:
        raise HTTPException(409, 'Save the Telegram connection first')
    try:
        language = message_settings(db, user.id)['language']
        send(row, MESSAGE_LANGUAGES[language]['test_message'])
    except RuntimeError as exc:
        row.last_error = str(exc)
        db.commit()
        raise HTTPException(502, str(exc)) from None
    row.last_error, row.last_sent_at = None, now()
    audit(db, actor, 'telegram.test', user.id)
    db.commit()
    return public(row)


def enqueue(db, alert, device, recovered=False):
    if alert.kind != 'unreachable':
        return
    db.flush()
    state = 'RECOVERED' if recovered else 'DOWN / TIMEOUT'
    for row in db.scalars(select(TelegramSettings).where(TelegramSettings.enabled.is_(True))):
        user = db.get(User, row.user_id)
        if not authorized(db, user, device.id):
            continue
        templates = message_settings(db, row.user_id)
        localized = MESSAGE_LANGUAGES[templates['language']]
        tower = db.get(Tower, device.tower_id)
        message = render_message(templates['recovery_message' if recovered else 'down_message'], {
            'status': localized['recovery_status' if recovered else 'down_status'],
            'device_name': device.name, 'ip_address': device.ip_address,
            'tower_name': tower.name if tower else '', 'time': now().isoformat()})
        key = hashlib.sha256((row.user_id + alert.id + state).encode()).hexdigest()
        db.add(TelegramNotification(user_id=row.user_id, device_id=device.id, event_key=key,
            message=message))


def dispatch(db):
    pending = db.scalars(select(TelegramNotification).where(
        TelegramNotification.sent_at.is_(None), TelegramNotification.attempts < 5,
        TelegramNotification.next_attempt <= now()).order_by(TelegramNotification.next_attempt).limit(5)).all()
    for item in pending:
        row = settings_for(db, item.user_id)
        user = db.get(User, item.user_id)
        if not row or not row.enabled or not authorized(db, user, item.device_id):
            db.delete(item)
            db.commit()
            continue
        item.attempts += 1
        try:
            send(row, item.message)
            item.sent_at = now()
            row.last_sent_at, row.last_error = now(), None
        except RuntimeError as exc:
            row.last_error = str(exc)
            item.next_attempt = now() + timedelta(seconds=min(900, 30 * 2 ** item.attempts))
        db.commit()
    db.execute(delete(TelegramNotification).where(TelegramNotification.sent_at < now() - timedelta(days=30)))
    db.commit()
