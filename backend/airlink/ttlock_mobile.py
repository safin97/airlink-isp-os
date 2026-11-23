"""Bluetooth work happens on the phone; only successful SDK results sync to cloud."""
from typing import Literal, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from . import ttlock as t
from .db import get_db
from .models import TTLockMobileOperation, audit
from .security import owner

router = APIRouter(prefix='/api/integrations/ttlock', dependencies=[Depends(t.private_response)], tags=['TTLock'])
KINDS = {
    'card': ('/v3/identityCard', 'card', 'cardNumber', '/v3/identityCard/list'),
    'fingerprint': ('/v3/fingerprint', 'fingerprint', 'fingerprintNumber', '/v3/fingerprint/list'),
    'passcode': ('/v3/keyboardPwd', 'keyboardPwd', 'keyboardPwd', '/v3/lock/listKeyboardPwd'),
}


def raw_lock(db, row, lock_id, page):
    data = t.cloud(db, row, '/v3/lock/list', {'pageNo': page, 'pageSize': 50})
    items = data.get('list')
    if not isinstance(items, list) or len(items) > 50:
        raise HTTPException(502, 'Invalid TTLock lock list.')
    for item in items:
        if isinstance(item, dict) and type(item.get('lockId')) is int and item['lockId'] == lock_id:
            return item
    raise HTTPException(404, 'Lock not found on this account page. Sync devices first.')


def sdk_data(lock):
    data = lock.get('lockData')
    if not isinstance(data, str) or not 1 <= len(data) <= 100000:
        raise HTTPException(409, 'TTLock did not provide Bluetooth credentials for this lock.')
    return data


def cards(db, row, lock_id, page, kind='card'):
    _, prefix, number, path = KINDS[kind]
    data = t.cloud(db, row, path, {'lockId': lock_id, 'pageNo': page, 'pageSize': 50, 'orderBy': 1})
    if (not isinstance(data.get('list'), list) or len(data['list']) > 50 or
        any(type(data.get(k)) is not int or data[k] < 0 for k in ('pages', 'total'))):
        raise HTTPException(502, 'Invalid TTLock card list.')
    items = []
    for item in data['list']:
        if (not isinstance(item, dict) or type(item.get(prefix + 'Id')) is not int or item[prefix + 'Id'] <= 0 or
            item.get('lockId') != lock_id or not isinstance(item.get(number), str)):
            raise HTTPException(502, 'Invalid TTLock credential information.')
        items.append({'id': item[prefix + 'Id'], 'number': item[number][:64],
            'name': str(item.get(prefix + 'Name') or kind.title())[:100],
            'start': item.get('startDate') if type(item.get('startDate')) is int else None,
            'end': item.get('endDate') if type(item.get('endDate')) is int else None,
            'cyclic': item.get(prefix + 'Type') not in (2, 3, '2', '3') if kind == 'passcode' else item.get(prefix + 'Type') == 4})
    return {'items': items, 'page': page, 'pages': data['pages'], 'total': data['total']}


@router.get('/locks/{lock_id}/credentials/{kind}')
def get_credentials(lock_id: int, kind: Literal['card', 'passcode', 'fingerprint'], page: int = Query(1, ge=1, le=10000),
                    lock_page: int = Query(1, ge=1, le=10000), user=Depends(owner), db=Depends(get_db)):
    t.limited(user, 'cards-read', 60)
    with t.guard(user):
        row = t.connection(db, user)
        raw_lock(db, row, lock_id, lock_page)
        result = cards(db, row, lock_id, page, kind)
        db.commit()
        return result


@router.get('/locks/{lock_id}/cards')
def get_cards(lock_id: int, page: int = Query(1, ge=1, le=10000), lock_page: int = Query(1, ge=1, le=10000),
              user=Depends(owner), db=Depends(get_db)):
    t.limited(user, 'cards-read', 60)
    with t.guard(user):
        row = t.connection(db, user)
        raw_lock(db, row, lock_id, lock_page)
        result = cards(db, row, lock_id, page)
        db.commit()
        return result


@router.get('/locks/{lock_id}/bluetooth')
def bluetooth(lock_id: int, page: int = Query(1, ge=1, le=10000), user=Depends(owner), db=Depends(get_db)):
    t.limited(user, 'bluetooth', 30)
    with t.guard(user):
        data = sdk_data(raw_lock(db, t.connection(db, user), lock_id, page))
        audit(db, user, 'ttlock.bluetooth.credentials', str(lock_id))
        db.commit()
        return {'lock_data': data}


class Prepare(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    request_id: str = Field(pattern=r'^[a-f0-9]{32}$')
    action: Literal['card_add', 'card_delete', 'card_period', 'passcode_add', 'passcode_delete', 'passcode_period',
                    'fingerprint_add', 'fingerprint_delete', 'fingerprint_period', 'lock_init', 'lock_reset']
    lock_id: Optional[int] = Field(default=None, gt=0)
    lock_page: int = Field(default=1, ge=1, le=10000)
    card_id: Optional[int] = Field(default=None, gt=0)
    card_page: int = Field(default=1, ge=1, le=10000)
    name: str = Field(default='', max_length=100)
    lock_mac: Optional[str] = Field(default=None, pattern=r'^(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$')
    passcode: Optional[SecretStr] = Field(default=None, min_length=4, max_length=9)
    start: int = Field(default=0, ge=0, le=4102444800000, strict=True)
    end: int = Field(default=0, ge=0, le=4102444800000, strict=True)

    @model_validator(mode='after')
    def valid_action(self):
        if self.action != 'lock_init' and self.lock_id is None:
            raise ValueError('Select a lock')
        if self.action == 'lock_init' and not self.lock_mac:
            raise ValueError('Select a nearby lock')
        if self.action.endswith(('_delete', '_period')) and self.card_id is None:
            raise ValueError('Select a card')
        if (self.action.endswith('_add') or self.action == 'lock_init') and not self.name:
            raise ValueError('Enter a name')
        if self.action.endswith(('_add', '_period')):
            if not ((self.start == self.end == 0 and self.action.endswith('_add')) or 0 < self.start < self.end):
                raise ValueError('Choose a valid access period')
        if self.action == 'passcode_add' and (self.passcode is None or not self.passcode.get_secret_value().isascii() or not self.passcode.get_secret_value().isdigit()):
            raise ValueError('Passcode must contain 4–9 digits')
        return self


@router.post('/mobile/prepare')
def prepare(data: Prepare, user=Depends(owner), db=Depends(get_db)):
    t.limited(user, 'mobile-write', 30)
    with t.guard(user):
        if db.get(TTLockMobileOperation, (user.id, data.request_id)):
            raise HTTPException(409, 'Operation already started. Check pending sync; do not repeat the Bluetooth action.')
        row = t.connection(db, user)
        payload = data.model_dump()
        payload['passcode'] = data.passcode.get_secret_value() if data.passcode else None
        credentials = t.decrypt(row.encrypted_credentials)
        payload['account_binding'] = [row.region, credentials['client_id'], credentials['username']]
        response = {'request_id': data.request_id}
        if data.action != 'lock_init':
            response['lock_data'] = sdk_data(raw_lock(db, row, data.lock_id, data.lock_page))
        if data.action.endswith(('_delete', '_period')):
            kind = data.action.split('_')[0]
            card = next((x for x in cards(db, row, data.lock_id, data.card_page, kind)['items'] if x['id'] == data.card_id), None)
            if card is None:
                raise HTTPException(404, 'Card not found on this lock. Refresh cards.')
            if data.action.endswith('_period') and card['cyclic']:
                raise HTTPException(409, 'This credential type must be edited in the TTLock app.')
            payload['card_number'] = card['number']
            response['card_number'] = card['number']
        operation = TTLockMobileOperation(user_id=user.id, request_id=data.request_id, lock_id=data.lock_id,
            action=data.action, status='prepared', encrypted_payload=t.encrypt(payload))
        db.add(operation)
        audit(db, user, 'ttlock.mobile.' + data.action + '.prepared', str(data.lock_id or 'new'))
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(409, 'Operation already started.') from None
        return response


class Complete(BaseModel):
    model_config = ConfigDict(extra='forbid')
    sdk_success: Literal[True]
    card_number: Optional[str] = Field(default=None, pattern=r'^[0-9]{1,32}$')
    fingerprint_number: Optional[str] = Field(default=None, pattern=r'^[0-9]{1,32}$')
    lock_data: Optional[SecretStr] = Field(default=None, min_length=1, max_length=100000)


def operation_for(db, user, request_id):
    op = db.get(TTLockMobileOperation, (user.id, request_id))
    if op is None:
        raise HTTPException(404, 'Operation not found.')
    return op


def sync_operation(db, user, op):
    if op.status == 'synced':
        return {'status': 'synced'}
    if op.status not in ('device_complete', 'sync_pending'):
        raise HTTPException(409, 'No successful Bluetooth result was received. Check the physical device.')
    row = t.connection(db, user)
    payload, result = t.decrypt(op.encrypted_payload), t.decrypt(op.encrypted_result)
    credentials = t.decrypt(row.encrypted_credentials)
    if payload['account_binding'] != [row.region, credentials['client_id'], credentials['username']]:
        raise HTTPException(409, 'Reconnect the original TTLock account to synchronize this operation.')
    if op.status == 'sync_pending' and cloud_has_result(db, row, op, payload, result):
        op.status = 'synced'
        audit(db, user, 'ttlock.mobile.reconciled', op.request_id)
        db.commit()
        return {'status': 'synced'}
    body = {'lockId': op.lock_id}
    kind, verb = op.action.split('_', 1)
    if kind in KINDS:
        base, prefix, number, _ = KINDS[kind]
        if verb == 'add':
            path = base + '/add'
            body.update({number: payload['passcode'] if kind == 'passcode' else result[kind + '_number'], prefix + 'Name': payload['name'],
                'startDate': payload['start'], 'endDate': payload['end']})
            if kind == 'fingerprint': body['fingerprintType'] = 1
            else: body['addType'] = 1
            if kind == 'passcode': body['keyboardPwdType'] = 2 if payload['start'] == payload['end'] == 0 else 3
        else:
            path = base + ('/delete' if verb == 'delete' else '/change' if kind == 'passcode' else '/changePeriod')
            body[prefix + 'Id'] = payload['card_id']
            if verb == 'delete': body['deleteType'] = 1
            else: body.update(startDate=payload['start'], endDate=payload['end'], changeType=1)
    elif op.action == 'lock_init':
        path = '/v3/lock/initialize'
        body = {'lockAlias': payload['name'], 'lockData': result['lock_data']}
    else:
        path = '/v3/lock/delete'
    # A recovery retries cloud synchronization only. It never moves a lock or
    # grants/revokes physical access again (all credential methods are type 1).
    op.status = 'sync_pending'
    db.commit()
    try:
        answer = t.cloud(db, row, path, body)
        key = KINDS[kind][1] + 'Id' if kind in KINDS and verb == 'add' else 'lockId' if op.action == 'lock_init' else 'errcode'
        if type(answer.get(key)) is not int or (answer[key] <= 0 if key != 'errcode' else answer[key] != 0):
            raise HTTPException(502, 'Unconfirmed cloud result')
    except HTTPException:
        audit(db, user, 'ttlock.mobile.sync_pending', op.request_id)
        db.commit()
        return {'status': 'sync_pending', 'message': 'Bluetooth succeeded; cloud sync is pending. Retry sync only, not the device action.'}
    op.status = 'synced'
    audit(db, user, 'ttlock.mobile.' + op.action + '.synced', op.request_id)
    db.commit()
    return {'status': 'synced'}


def cloud_has_result(db, row, op, payload, result):
    """Reconcile an ambiguous response before retrying cloud-only registration."""
    kind, verb = op.action.split('_', 1)
    for page in range(1, 201):
        if kind in KINDS:
            listing = cards(db, row, op.lock_id, page, kind)
            for item in listing['items']:
                if verb == 'add':
                    number = payload['passcode'] if kind == 'passcode' else result[kind + '_number']
                    if item['number'] == number and item['name'] == payload['name'] and item['start'] == payload['start'] and item['end'] == payload['end']:
                        return True
                elif item['id'] == payload['card_id']:
                    return verb == 'period' and item['start'] == payload['start'] and item['end'] == payload['end']
        else:
            listing = t.cloud(db, row, '/v3/lock/list', {'pageNo': page, 'pageSize': 50})
            if not isinstance(listing.get('list'), list) or type(listing.get('pages')) is not int:
                raise HTTPException(502, 'Unable to reconcile cloud lock list.')
            for item in listing['list']:
                if verb == 'init' and str(item.get('lockMac', '')).lower() == payload['lock_mac'].lower():
                    return True
                if verb == 'reset' and item.get('lockId') == op.lock_id:
                    return False
        if page >= listing['pages']:
            return verb in ('delete', 'reset')
    raise HTTPException(409, 'Too many records to reconcile automatically. Check the TTLock account before retrying.')


@router.post('/mobile/{request_id}/complete')
def complete(request_id: str, data: Complete, user=Depends(owner), db=Depends(get_db)):
    t.limited(user, 'mobile-sync', 60)
    with t.guard(user):
        op = operation_for(db, user, request_id)
        result = {'card_number': data.card_number, 'fingerprint_number': data.fingerprint_number,
            'lock_data': data.lock_data.get_secret_value() if data.lock_data else None}
        if op.status != 'prepared':
            if op.encrypted_result and t.decrypt(op.encrypted_result) != result:
                raise HTTPException(409, 'This operation already has a different result.')
            return sync_operation(db, user, op)
        if (op.action == 'card_add' and not data.card_number) or (op.action == 'fingerprint_add' and not data.fingerprint_number) or (op.action == 'lock_init' and data.lock_data is None):
            raise HTTPException(422, 'Missing Bluetooth SDK result.')
        op.encrypted_result = t.encrypt(result)
        op.status = 'device_complete'
        audit(db, user, 'ttlock.mobile.device_complete', request_id)
        db.commit()
        return sync_operation(db, user, op)


@router.post('/mobile/{request_id}/sync')
def sync(request_id: str, user=Depends(owner), db=Depends(get_db)):
    t.limited(user, 'mobile-sync', 60)
    with t.guard(user):
        return sync_operation(db, user, operation_for(db, user, request_id))


@router.get('/mobile/pending')
def pending(user=Depends(owner), db=Depends(get_db)):
    rows = db.scalars(select(TTLockMobileOperation).where(TTLockMobileOperation.user_id == user.id,
        TTLockMobileOperation.status != 'synced').order_by(TTLockMobileOperation.created_at.desc()).limit(100)).all()
    return {'items': [{'request_id': x.request_id, 'lock_id': x.lock_id, 'action': x.action,
        'status': x.status, 'created_at': x.created_at.isoformat()} for x in rows]}


@router.put('/locks/{lock_id}/cards/{card_id}/name')
def rename_card(lock_id: int, card_id: int, data: t.RenameInput, lock_page: int = Query(1, ge=1, le=10000),
                kind: Literal['card', 'passcode', 'fingerprint'] = 'card', user=Depends(owner), db=Depends(get_db)):
    t.limited(user, 'card-rename', 30)
    with t.guard(user):
        row = t.connection(db, user)
        raw_lock(db, row, lock_id, lock_page)
        if card_id not in {x['id'] for x in cards(db, row, lock_id, data.page, kind)['items']}:
            raise HTTPException(404, 'Card not found on this lock.')
        base, prefix, _, _ = KINDS[kind]
        result = t.cloud(db, row, base + ('/change' if kind == 'passcode' else '/rename'), {'lockId': lock_id, prefix + 'Id': card_id, prefix + 'Name': data.name})
        if type(result.get('errcode')) is not int or result['errcode'] != 0:
            raise HTTPException(502, 'TTLock did not confirm the rename. Refresh cards.')
        audit(db, user, 'ttlock.card.rename', str(card_id))
        db.commit()
        return {'id': card_id, 'name': data.name}


@router.put('/locks/{lock_id}/credentials/{kind}/{card_id}/name')
def rename_credential(lock_id: int, kind: Literal['card', 'passcode', 'fingerprint'], card_id: int, data: t.RenameInput,
                      lock_page: int = Query(1, ge=1, le=10000), user=Depends(owner), db=Depends(get_db)):
    return rename_card(lock_id, card_id, data, lock_page, kind, user, db)
