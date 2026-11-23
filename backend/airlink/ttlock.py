"""Owner-scoped TTLock Cloud access; secrets and lock data stay server-side."""
import hashlib
import json
import threading
import time
from datetime import timedelta
from typing import Literal, Optional
import httpx
from cryptography.fernet import InvalidToken
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from sqlalchemy import select
from .db import get_db
from .models import TTLockConnection, TTLockCommand, TTLockApplication, now, audit
from .security import owner, cipher, aware

def private_response(response: Response):
    response.headers['Cache-Control'] = 'no-store'


router = APIRouter(dependencies=[Depends(private_response)], prefix='/api/integrations/ttlock', tags=['TTLock'])
REGIONS = {'eu': 'https://euapi.ttlock.com', 'cn': 'https://cnapi.ttlock.com'}
PATHS = {'/oauth2/token', '/v3/lock/list', '/v3/lock/queryOpenState', '/v3/lock/lock', '/v3/lock/unlock', '/v3/lock/rename'}
READ_PATHS = {'/v3/lock/list', '/v3/lock/queryOpenState', '/v3/identityCard/list'}
READ_PATHS.update({'/v3/fingerprint/list', '/v3/lock/listKeyboardPwd'})
PATHS.update(READ_PATHS | {'/v3/identityCard/add', '/v3/identityCard/delete', '/v3/identityCard/rename',
    '/v3/identityCard/changePeriod', '/v3/lock/initialize', '/v3/lock/delete'})
PATHS.update({'/v3/fingerprint/' + x for x in ('add', 'delete', 'changePeriod', 'rename')})
PATHS.update({'/v3/keyboardPwd/' + x for x in ('add', 'delete', 'change')})
GUARDS = [threading.RLock() for _ in range(64)]


class ApplicationInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    region: Literal['eu', 'cn'] = 'eu'
    client_id: str = Field(min_length=1, max_length=128, pattern=r'^[A-Za-z0-9_-]+$')
    client_secret: SecretStr = Field(min_length=1, max_length=1024)


class ConnectionInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    username: str = Field(min_length=1, max_length=254)
    password: SecretStr = Field(min_length=1, max_length=1024)
    region: Optional[Literal['eu', 'cn']] = None
    client_id: Optional[str] = Field(default=None, min_length=1, max_length=128, pattern=r'^[A-Za-z0-9_-]+$')
    client_secret: Optional[SecretStr] = Field(default=None, min_length=1, max_length=1024)


class ActionInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    action: Literal['lock', 'unlock']
    request_id: str = Field(pattern=r'^[a-f0-9]{32}$')
    page: int = Field(default=1, ge=1, le=10000)


class RenameInput(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=100)
    page: int = Field(default=1, ge=1, le=10000)


def guard(user):
    return GUARDS[int(hashlib.sha256(user.id.encode()).hexdigest(), 16) % len(GUARDS)]


def limited(user, action, count=30):
    from .api import limited as enforce
    enforce('ttlock:' + user.id + ':' + action, count)


def encrypt(value):
    return cipher().encrypt(json.dumps(value).encode()).decode()


def decrypt(value):
    try:
        result = json.loads(cipher().decrypt(value.encode()))
        if not isinstance(result, dict):
            raise ValueError()
        return result
    except (InvalidToken, ValueError, TypeError):
        raise HTTPException(409, 'Reconnect TTLock; saved credentials could not be opened.') from None


class ExpiredToken(Exception):
    pass


def request(region, path, body, transport=None):
    if region not in REGIONS or path not in PATHS:
        raise ValueError('Unsupported TTLock operation')
    try:
        with httpx.Client(timeout=httpx.Timeout(20, connect=5), follow_redirects=False,
                          trust_env=False, transport=transport) as client:
            method = 'GET' if path in READ_PATHS else 'POST'
            params = {'params': body} if method == 'GET' else {'data': body}
            with client.stream(method, REGIONS[region] + path, **params) as response:
                if response.status_code != 200:
                    raise HTTPException(502, 'TTLock is unavailable or rejected access. Check your region and connection.')
                raw = bytearray()
                for chunk in response.iter_bytes():
                    raw.extend(chunk)
                    if len(raw) > 2 * 1024 * 1024:
                        raise HTTPException(502, 'TTLock returned too much data.')
                data = json.loads(raw)
    except (httpx.HTTPError, ValueError):
        raise HTTPException(502, 'TTLock could not be reached. Try refreshing or reconnecting.') from None
    if not isinstance(data, dict):
        raise HTTPException(502, 'TTLock returned an invalid response.')
    code = data.get('errcode', 0)
    if type(code) is not int:
        raise HTTPException(502, 'TTLock returned an invalid response.')
    if code == 10004:
        raise ExpiredToken()
    if code != 0:
        message = ('Enable Remote Unlock in the TTLock app and check your gateway or Wi-Fi lock connection.'
                   if code == -4043 else 'TTLock rejected the request. Check your app account, region, application credentials and lock permissions.')
        raise HTTPException(502, message)
    return data


def token_data(result):
    if not all(isinstance(result.get(k), str) and 0 < len(result[k]) <= 4096 for k in ('access_token', 'refresh_token')):
        raise HTTPException(502, 'TTLock did not return a valid session. Reconnect your account.')
    seconds = result.get('expires_in')
    if type(seconds) is not int or not 60 <= seconds <= 366 * 86400:
        raise HTTPException(502, 'TTLock returned an invalid session expiry.')
    return {k: result[k] for k in ('access_token', 'refresh_token')}, now() + timedelta(seconds=seconds)


def connection(db, user):
    row = db.scalar(select(TTLockConnection).where(TTLockConnection.user_id == user.id).with_for_update())
    if row is None:
        raise HTTPException(409, 'Connect your TTLock account first.')
    return row


def refresh(db, row, credentials, token):
    try:
        data = request(row.region, '/oauth2/token', {'clientId': credentials['client_id'],
            'clientSecret': credentials['client_secret'], 'grant_type': 'refresh_token', 'refresh_token': token['refresh_token']})
    except ExpiredToken:
        raise HTTPException(409, 'Your TTLock session expired. Reconnect your account.') from None
    token, row.token_expires = token_data(data)
    row.encrypted_token = encrypt(token)
    db.flush()
    return token


def cloud(db, row, path, body):
    credentials, token = decrypt(row.encrypted_credentials), decrypt(row.encrypted_token)
    if aware(row.token_expires) <= now() + timedelta(seconds=60):
        token = refresh(db, row, credentials, token)
    payload = {**body, 'clientId': credentials['client_id'], 'accessToken': token['access_token'], 'date': int(time.time() * 1000)}
    try:
        return request(row.region, path, payload)
    except ExpiredToken:
        # Retry reads only; never automatically replay a cloud mutation.
        if path not in READ_PATHS:
            raise HTTPException(409, 'TTLock access expired. Refresh lock status before starting another action.') from None
        token = refresh(db, row, credentials, token)
        payload['accessToken'] = token['access_token']
        payload['date'] = int(time.time() * 1000)
        try:
            return request(row.region, path, payload)
        except ExpiredToken:
            raise HTTPException(409, 'Reconnect your TTLock account.') from None


def lock_list(db, row, page):
    data = cloud(db, row, '/v3/lock/list', {'pageNo': page, 'pageSize': 50})
    if not isinstance(data.get('list'), list) or len(data['list']) > 50:
        raise HTTPException(502, 'TTLock returned an invalid lock list.')
    for key in ('pages', 'total'):
        if type(data.get(key)) is not int or data[key] < 0:
            raise HTTPException(502, 'TTLock returned invalid pagination.')
    items = []
    for item in data['list']:
        if not isinstance(item, dict) or type(item.get('lockId')) is not int or item['lockId'] <= 0:
            raise HTTPException(502, 'TTLock returned invalid lock information.')
        battery = item.get('electricQuantity')
        items.append({'id': item['lockId'], 'name': str(item.get('lockAlias') or item.get('lockName') or item['lockId'])[:200],
            'battery': battery if type(battery) is int and 0 <= battery <= 100 else None,
            'has_gateway': item.get('hasGateway') == 1, 'group': str(item.get('groupName') or '')[:200]})
    return {'items': items, 'page': page, 'pages': data['pages'], 'total': data['total'], 'observed_at': now().isoformat()}


def require_lock(db, row, lock_id, page):
    if lock_id <= 0 or lock_id not in {item['id'] for item in lock_list(db, row, page)['items']}:
        raise HTTPException(404, 'Lock not found on this account page. Refresh the lock list.')


def status(row):
    if row is None:
        return {'configured': False}
    credentials = decrypt(row.encrypted_credentials)
    return {'configured': True, 'region': row.region, 'username': credentials['username'],
            'client_id': credentials['client_id'], 'expires_at': aware(row.token_expires).isoformat()}


def application(db, user):
    saved = db.get(TTLockApplication, user.id)
    if saved:
        return saved.region, decrypt(saved.encrypted_credentials)
    saved = db.get(TTLockConnection, user.id)
    if saved:
        return saved.region, decrypt(saved.encrypted_credentials)
    return None


def save_application(db, user, region, credentials):
    saved = db.get(TTLockApplication, user.id)
    if saved is None:
        saved = TTLockApplication(user_id=user.id)
        db.add(saved)
    saved.region = region
    saved.encrypted_credentials = encrypt({key: credentials[key] for key in ('client_id', 'client_secret')})


@router.get('/application')
def get_application(user=Depends(owner), db=Depends(get_db)):
    saved = application(db, user)
    return {'configured': False} if saved is None else {'configured': True, 'region': saved[0], 'client_id': saved[1]['client_id']}


@router.put('/application')
def set_application(data: ApplicationInput, user=Depends(owner), db=Depends(get_db)):
    with guard(user):
        save_application(db, user, data.region, {'client_id': data.client_id, 'client_secret': data.client_secret.get_secret_value()})
        audit(db, user, 'ttlock.application.save')
        db.commit()
    return {'configured': True, 'region': data.region, 'client_id': data.client_id}


@router.get('')
def get_connection(user=Depends(owner), db=Depends(get_db)):
    return status(db.get(TTLockConnection, user.id))


@router.put('')
def connect(data: ConnectionInput, user=Depends(owner), db=Depends(get_db)):
    limited(user, 'login', 10)
    with guard(user):
        if data.client_id is not None or data.client_secret is not None or data.region is not None:
            if not data.client_id or data.client_secret is None or data.region is None:
                raise HTTPException(422, 'Complete the TTLock application setup before signing in.')
            region = data.region
            credentials = {'client_id': data.client_id, 'client_secret': data.client_secret.get_secret_value()}
        else:
            saved = application(db, user)
            if saved is None:
                raise HTTPException(409, 'Complete the one-time TTLock integration setup first. TTLock requires an approved Client ID and Client Secret before username/password login is available.')
            region, credentials = saved
        credentials = {**credentials, 'username': data.username}
        try:
            result = request(region, '/oauth2/token', {'clientId': credentials['client_id'],
                'clientSecret': credentials['client_secret'], 'username': data.username,
                'password': hashlib.md5(data.password.get_secret_value().encode()).hexdigest()})
        except ExpiredToken:
            raise HTTPException(502, 'TTLock rejected the login.') from None
        token, expires = token_data(result)
        # Validate access before replacing a working connection.
        candidate = TTLockConnection(user_id=user.id, region=region, encrypted_credentials=encrypt(credentials),
            encrypted_token=encrypt(token), token_expires=expires)
        listing = lock_list(db, candidate, 1)
        row = db.get(TTLockConnection, user.id)
        if row is None:
            row = candidate
            db.add(row)
        else:
            row.region, row.encrypted_credentials = candidate.region, candidate.encrypted_credentials
            row.encrypted_token, row.token_expires = candidate.encrypted_token, candidate.token_expires
        save_application(db, user, region, credentials)
        audit(db, user, 'ttlock.connect')
        db.commit()
        return {**status(row), 'locks': listing}


@router.delete('')
def disconnect(user=Depends(owner), db=Depends(get_db)):
    with guard(user):
        row = db.get(TTLockConnection, user.id)
        if row:
            db.delete(row)
            audit(db, user, 'ttlock.disconnect')
            db.commit()
        return {'configured': False}


@router.get('/locks')
def locks(page: int = Query(1, ge=1, le=10000), user=Depends(owner), db=Depends(get_db)):
    limited(user, 'read', 60)
    with guard(user):
        result = lock_list(db, connection(db, user), page)
        db.commit()
        return result


@router.get('/locks/{lock_id}/state')
def state(lock_id: int, page: int = Query(1, ge=1, le=10000), user=Depends(owner), db=Depends(get_db)):
    limited(user, 'read', 60)
    with guard(user):
        row = connection(db, user)
        require_lock(db, row, lock_id, page)
        result = cloud(db, row, '/v3/lock/queryOpenState', {'lockId': lock_id})
        value = result.get('state')
        db.commit()
        return {'id': lock_id, 'state': {0: 'locked', 1: 'unlocked', 2: 'unknown'}.get(value, 'unknown')
                if type(value) is int else 'unknown', 'observed_at': now().isoformat()}


@router.post('/locks/{lock_id}/action')
def action(lock_id: int, data: ActionInput, user=Depends(owner), db=Depends(get_db)):
    limited(user, 'action', 20)
    with guard(user):
        prior = db.get(TTLockCommand, (user.id, data.request_id))
        if prior:
            if prior.lock_id != lock_id or prior.action != data.action:
                raise HTTPException(409, 'This request ID was already used for another lock action.')
            if prior.status != 'completed':
                raise HTTPException(409, 'This action was already submitted. Check lock status before starting another action.')
            return {'id': lock_id, 'action': data.action, 'status': 'completed'}
        row = connection(db, user)
        require_lock(db, row, lock_id, data.page)
        command = TTLockCommand(user_id=user.id, request_id=data.request_id, lock_id=lock_id,
                                action=data.action, status='submitted')
        db.add(command)
        audit(db, user, 'ttlock.' + data.action + '.requested', str(lock_id))
        db.commit()  # Durable deduplication before sending the physical command.
        try:
            result = cloud(db, row, '/v3/lock/' + data.action, {'lockId': lock_id})
            if type(result.get('errcode')) is not int or result['errcode'] != 0:
                raise HTTPException(502, 'TTLock did not confirm the action.')
        except HTTPException:
            command.status = 'unconfirmed'
            audit(db, user, 'ttlock.' + data.action + '.unconfirmed', str(lock_id))
            db.commit()
            raise HTTPException(502, 'TTLock did not confirm the result. Check the physical lock or refresh its status before trying again.') from None
        command.status = 'completed'
        audit(db, user, 'ttlock.' + data.action + '.completed', str(lock_id))
        db.commit()
        return {'id': lock_id, 'action': data.action, 'status': 'completed'}


@router.put('/locks/{lock_id}/name')
def rename(lock_id: int, data: RenameInput, user=Depends(owner), db=Depends(get_db)):
    limited(user, 'rename', 20)
    with guard(user):
        row = connection(db, user)
        require_lock(db, row, lock_id, data.page)
        audit(db, user, 'ttlock.rename.requested', str(lock_id))
        db.commit()
        try:
            result = cloud(db, row, '/v3/lock/rename', {'lockId': lock_id, 'lockAlias': data.name})
            if type(result.get('errcode')) is not int or result['errcode'] != 0:
                raise HTTPException(502, 'TTLock did not confirm the rename.')
        except HTTPException:
            audit(db, user, 'ttlock.rename.unconfirmed', str(lock_id))
            db.commit()
            raise HTTPException(502, 'TTLock did not confirm the name change. Sync devices to check the current name before trying again.') from None
        audit(db, user, 'ttlock.rename.completed', str(lock_id))
        db.commit()
        return {'id': lock_id, 'name': data.name}
