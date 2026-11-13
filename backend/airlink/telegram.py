"""Account-scoped Telegram delivery. Tokens never leave the server API."""
from typing import Optional
import json
import hashlib
import urllib.request
from datetime import timedelta
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy import select, delete
from .db import get_db
from .models import TelegramSettings, TelegramNotification, User, Device, now, audit
from .security import current_user, cipher
from . import section_access

router = APIRouter(prefix='/api/integrations/telegram', tags=['Telegram'])

def account(user=Depends(current_user)):
    if user.role not in ('owner', 'manager'):
        raise HTTPException(403, 'Owner or manager account required')
    return user


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

@router.get('')
def status(user=Depends(account), db=Depends(get_db)):
    return public(settings_for(db, user.id))

@router.put('')
def save(data: SettingsInput, user=Depends(account), db=Depends(get_db)):
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
    audit(db, user, 'telegram.configure')
    db.commit()
    return public(row)

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

@router.post('/test')
def test_message(user=Depends(account), db=Depends(get_db)):
    row = settings_for(db, user.id)
    if row is None:
        raise HTTPException(409, 'Save the Telegram connection first')
    try:
        send(row, 'AirLink: Telegram notifications are connected.')
    except RuntimeError as exc:
        row.last_error = str(exc)
        db.commit()
        raise HTTPException(502, str(exc)) from None
    row.last_error, row.last_sent_at = None, now()
    audit(db, user, 'telegram.test')
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
        key = hashlib.sha256((row.user_id + alert.id + state).encode()).hexdigest()
        db.add(TelegramNotification(user_id=row.user_id, device_id=device.id, event_key=key,
            message=f'AirLink — {state}\nDevice: {device.name}\nIP: {device.ip_address}\nTime: {now().isoformat()}'))


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
