"""Owner-scoped, foreground phone relay. No server-side Bluetooth execution."""
import hashlib
import json
import secrets
from datetime import timedelta
from typing import Literal
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from . import ttlock as t, ttlock_mobile as mobile
from .db import get_db
from .models import TTLockBridge, TTLockBridgeJob, audit, now
from .security import owner, aware

router = APIRouter(prefix='/api/integrations/ttlock/bridge',
    dependencies=[Depends(t.private_response)], tags=['TTLock'])
TERMINAL = {'succeeded', 'failed', 'unknown', 'cancelled', 'expired'}


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def binding(db, user):
    row = t.connection(db, user)
    credentials = t.decrypt(row.encrypted_credentials)
    return {'region': row.region, 'client_id': credentials['client_id'], 'username': credentials['username']}


def get_bridge(db, user, bridge_id, token=None):
    bridge = db.get(TTLockBridge, bridge_id)
    if bridge is None or bridge.user_id != user.id:
        raise HTTPException(404, 'Bluetooth phone not found.')
    if token is not None and not secrets.compare_digest(bridge.token_hash, digest(token)):
        raise HTTPException(403, 'This phone session is no longer authorized.')
    if t.decrypt(bridge.encrypted_binding) != binding(db, user):
        raise HTTPException(409, 'Reconnect the original TTLock account and restart phone sharing.')
    return bridge


def get_job(db, user, job_id):
    job = db.get(TTLockBridgeJob, job_id)
    if job is None or job.user_id != user.id:
        raise HTTPException(404, 'Bluetooth request not found.')
    return job


def expire(db, job):
    if job.status in ('queued', 'running') and aware(job.expires_at) <= now():
        db.execute(update(TTLockBridgeJob).where(TTLockBridgeJob.id == job.id,
            TTLockBridgeJob.status == job.status, TTLockBridgeJob.expires_at <= now()).values(
                status='expired' if job.status == 'queued' else 'unknown').execution_options(synchronize_session='fetch'))
        db.refresh(job)
    if job.status in TERMINAL:
        db.execute(update(TTLockBridge).where(TTLockBridge.id == job.bridge_id,
            TTLockBridge.active_job_id == job.id).values(active_job_id=None))


class Register(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=80)


@router.post('/phones')
def register(data: Register, user=Depends(owner), db=Depends(get_db)):
    t.limited(user, 'bridge-register', 10)
    token, bridge_id = secrets.token_hex(32), secrets.token_hex(16)
    db.add(TTLockBridge(id=bridge_id, user_id=user.id, name=data.name,
        token_hash=digest(token), encrypted_binding=t.encrypt(binding(db, user)),
        expires_at=now() + timedelta(seconds=120)))
    audit(db, user, 'ttlock.bridge.started', bridge_id)
    db.commit()
    return {'id': bridge_id, 'token': token}


@router.get('/phones')
def phones(user=Depends(owner), db=Depends(get_db)):
    t.limited(user, 'bridge-list', 120)
    current = binding(db, user)
    rows = db.scalars(select(TTLockBridge).where(TTLockBridge.user_id == user.id,
        TTLockBridge.expires_at > now()).order_by(TTLockBridge.expires_at.desc()).limit(20))
    return {'items': [{'id': b.id, 'name': b.name, 'expires_at': b.expires_at.isoformat()}
        for b in rows if t.decrypt(b.encrypted_binding) == current]}


@router.post('/phones/{bridge_id}/poll')
def poll(bridge_id: str, x_airlink_bridge: str = Header(min_length=64, max_length=64), user=Depends(owner), db=Depends(get_db)):
    t.limited(user, 'bridge-poll', 120)
    with t.guard(user):
        bridge = get_bridge(db, user, bridge_id, x_airlink_bridge)
        # A stopped bridge has a revoked token; a temporarily sleeping phone can resume.
        bridge.expires_at = now() + timedelta(seconds=120)
        result = None
        if bridge.active_job_id:
            job = get_job(db, user, bridge.active_job_id)
            expire(db, job)
            if job.status == 'queued':
                payload = t.decrypt(job.encrypted_payload)
                params = payload['parameters']
                # Do not deliver passcodes or hardware credentials until explicit claim.
                result = {'id': job.id, 'lock_name': payload['lock_name'],
                    'action': params['action'], 'name': params.get('name'),
                    'credential_id': params.get('card_id'), 'start': params.get('start'), 'end': params.get('end')}
        db.commit()
        return {'job': result}


@router.delete('/phones/{bridge_id}')
def stop(bridge_id: str, x_airlink_bridge: str = Header(min_length=64, max_length=64), user=Depends(owner), db=Depends(get_db)):
    with t.guard(user):
        bridge = get_bridge(db, user, bridge_id, x_airlink_bridge)
        bridge.expires_at = now()
        bridge.token_hash = digest(secrets.token_hex(32))
        if bridge.active_job_id:
            job = get_job(db, user, bridge.active_job_id)
            changed = db.execute(update(TTLockBridgeJob).where(TTLockBridgeJob.id == job.id,
                TTLockBridgeJob.status == 'queued').values(status='cancelled'))
            if changed.rowcount == 1:
                bridge.active_job_id = None
        audit(db, user, 'ttlock.bridge.stopped', bridge.id)
        db.commit()
        return {'status': 'stopped'}


class Command(BaseModel):
    model_config = ConfigDict(extra='forbid')
    action: Literal['lock', 'unlock', 'status', 'battery', 'time', 'records']
    lock_id: int = Field(gt=0)
    lock_page: int = Field(default=1, ge=1, le=10000)


class Enqueue(BaseModel):
    model_config = ConfigDict(extra='forbid')
    request_id: str = Field(pattern=r'^[a-f0-9]{32}$')
    bridge_id: str = Field(pattern=r'^[a-f0-9]{32}$')
    parameters: dict


@router.post('/jobs')
def enqueue(data: Enqueue, user=Depends(owner), db=Depends(get_db)):
    t.limited(user, 'bridge-write', 30)
    if len(json.dumps(data.parameters)) > 2048:
        raise HTTPException(422, 'Bluetooth request is too large.')
    try:
        if data.parameters.get('action') in ('lock', 'unlock', 'status', 'battery', 'time', 'records'):
            params = Command.model_validate(data.parameters).model_dump()
            operation = False
        else:
            parsed = mobile.Prepare.model_validate({**data.parameters, 'request_id': data.request_id})
            if parsed.action == 'lock_init':
                raise ValueError('Pair new locks on the phone')
            params = parsed.model_dump()
            params['passcode'] = parsed.passcode.get_secret_value() if parsed.passcode else None
            operation = True
    except (ValidationError, ValueError):
        raise HTTPException(422, 'Invalid Bluetooth action or credential details. Pair new locks directly in the phone app.') from None
    with t.guard(user):
        bridge = get_bridge(db, user, data.bridge_id)
        if aware(bridge.expires_at) <= now():
            raise HTTPException(409, 'Phone is offline. Open Bluetooth sharing in the AirLink app.')
        if db.get(TTLockBridgeJob, data.request_id):
            raise HTTPException(409, 'Request already exists. Check its result; do not repeat it.')
        if bridge.active_job_id:
            expire(db, get_job(db, user, bridge.active_job_id))
        lock = mobile.raw_lock(db, t.connection(db, user), params['lock_id'], params['lock_page'])
        reserved = db.execute(update(TTLockBridge).where(TTLockBridge.id == bridge.id,
            TTLockBridge.active_job_id.is_(None)).values(active_job_id=data.request_id))
        if reserved.rowcount != 1:
            raise HTTPException(409, 'This phone has a pending request. Finish or cancel it first.')
        db.add(TTLockBridgeJob(id=data.request_id, user_id=user.id, bridge_id=bridge.id,
            status='queued', expires_at=now() + timedelta(seconds=120),
            encrypted_payload=t.encrypt({'parameters': params, 'operation': operation,
                'lock_name': str(lock.get('lockAlias') or lock.get('lockName') or params['lock_id'])[:100]})))
        audit(db, user, 'ttlock.bridge.queued', data.request_id)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(409, 'Request already exists.') from None
        return {'id': data.request_id, 'status': 'queued'}


@router.get('/jobs/{job_id}')
def result(job_id: str, user=Depends(owner), db=Depends(get_db)):
    t.limited(user, 'bridge-result', 180)
    job = get_job(db, user, job_id)
    expire(db, job)
    data = {'id': job.id, 'status': job.status}
    if job.encrypted_result:
        data['result'] = t.decrypt(job.encrypted_result)
    db.commit()
    return data


@router.post('/jobs/{job_id}/cancel')
def cancel(job_id: str, user=Depends(owner), db=Depends(get_db)):
    job = get_job(db, user, job_id)
    changed = db.execute(update(TTLockBridgeJob).where(TTLockBridgeJob.id == job.id,
        TTLockBridgeJob.status == 'queued').values(status='cancelled'))
    if changed.rowcount != 1:
        raise HTTPException(409, 'Request already started or finished. Inspect the phone and lock.')
    db.refresh(job)
    expire(db, job)
    db.commit()
    return {'status': 'cancelled'}


@router.post('/jobs/{job_id}/claim')
def claim(job_id: str, x_airlink_bridge: str = Header(min_length=64, max_length=64), user=Depends(owner), db=Depends(get_db)):
    t.limited(user, 'bridge-claim', 30)
    with t.guard(user):
        job = get_job(db, user, job_id)
        bridge = get_bridge(db, user, job.bridge_id, x_airlink_bridge)
        if aware(bridge.expires_at) <= now():
            raise HTTPException(409, 'Resume Bluetooth sharing before approving.')
        payload = t.decrypt(job.encrypted_payload)
        params = payload['parameters']
        mobile.raw_lock(db, t.connection(db, user), params['lock_id'], params['lock_page'])
        token = secrets.token_hex(32)
        live_phone = select(TTLockBridge.id).where(TTLockBridge.id == bridge.id,
            TTLockBridge.expires_at > now(), TTLockBridge.token_hash == digest(x_airlink_bridge)).exists()
        changed = db.execute(update(TTLockBridgeJob).where(TTLockBridgeJob.id == job.id,
            TTLockBridgeJob.status == 'queued', TTLockBridgeJob.expires_at > now(), live_phone).values(
                status='running', claim_hash=digest(token), expires_at=now() + timedelta(seconds=240))
                .execution_options(synchronize_session='fetch'))
        if changed.rowcount != 1:
            raise HTTPException(409, 'Request already claimed, cancelled or expired. Never repeat its Bluetooth action.')
        audit(db, user, 'ttlock.bridge.claimed', job.id)
        db.commit()
        return {**payload, 'claim_token': token}


class Completion(BaseModel):
    model_config = ConfigDict(extra='forbid')
    claim_token: str = Field(pattern=r'^[a-f0-9]{64}$')
    status: Literal['succeeded', 'failed', 'unknown']
    result: dict = Field(default_factory=dict)


@router.post('/jobs/{job_id}/complete')
def complete(job_id: str, data: Completion, user=Depends(owner), db=Depends(get_db)):
    t.limited(user, 'bridge-complete', 60)
    if len(json.dumps(data.result)) > 200000 or set(data.result) - {'status', 'message', 'battery', 'time', 'state', 'records'}:
        raise HTTPException(422, 'Invalid Bluetooth result.')
    with t.guard(user):
        job = get_job(db, user, job_id)
        if not job.claim_hash or not secrets.compare_digest(job.claim_hash, digest(data.claim_token)):
            raise HTTPException(403, 'Invalid phone claim.')
        payload = {'status': data.status, 'data': data.result}
        if job.encrypted_result:
            if t.decrypt(job.encrypted_result) != payload:
                raise HTTPException(409, 'A different result was already recorded.')
            return {'status': job.status}
        if job.status not in ('running', 'unknown'):
            raise HTTPException(409, 'Request has not started.')
        changed = db.execute(update(TTLockBridgeJob).where(TTLockBridgeJob.id == job.id,
            TTLockBridgeJob.encrypted_result.is_(None), TTLockBridgeJob.status.in_(('running', 'unknown')))
            .values(encrypted_result=t.encrypt(payload), status=data.status))
        db.refresh(job)
        if changed.rowcount != 1 and (not job.encrypted_result or t.decrypt(job.encrypted_result) != payload):
            raise HTTPException(409, 'A different result was already recorded.')
        expire(db, job)
        audit(db, user, 'ttlock.bridge.' + job.status, job.id)
        db.commit()
        return {'status': job.status}
