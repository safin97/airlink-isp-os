import asyncio
import csv
import io
import json
import secrets
import socket
import jwt
from contextlib import asynccontextmanager, suppress
import os
from datetime import timedelta
from typing import Optional
from fastapi import FastAPI, Depends, HTTPException, Request, Response, WebSocket, WebSocketDisconnect, Query
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.responses import JSONResponse
from sqlalchemy import select, func, text, delete, update, or_, case
from sqlalchemy.exc import IntegrityError
from redis import Redis
from redis.exceptions import RedisError
from . import device_management, device_access, online_device, snmp_visibility, device_login_profiles
from . import towers_device_access, drive_backups
from . import __version__, discovery, sas4, payments, tower_api, section_access, manager_places, access_roles, manager_parents, sas4_reports
from .customer_probes import service as customer_probe_service
from .customer_collector import service as customer_collector_service
from .registration_usernames import service as registration_username_service
from .wireless_clients import public_clients
from . import snmp_discovery
from .schemas import SNMPDiscoveryInput, SNMPPublicProfileInput, DeviceSNMPAssignment
from .system_stats import service as system_stats_service
from .vendor_identity import VENDOR_LABELS
from .config import settings
from .db import get_db, SessionLocal
from .models import (User, Role, Initialization, LoginSession, RefreshToken, Tower, Place, TowerPlace, ManagerPlace, Sector, Device, DeviceOutage,
                     UserSectionAccess, UserSectionEdits, UserSectionDeletes, UserManagerRole, UserAccessRole, DeviceAssignment, SNMPProfile, Metric, Alert, Interface, NetworkLink, UpdateHistory, AuditLog, now, audit)
from .security import (hasher, dummy_hash, verify_password, digest, aware, access_token, issue_refresh,
                       current_user, owner, settings_access, updates_access, resolve_user, cipher, bearer)
from .schemas import WirelessSSIDInput, SNMPDiscoveryProfileInput, Login, Setup, UserInput, PlaceInput, TowerInput, SectorInput, DeviceInput, ProfileInput, LinkInput, DiscoveryInput, ManagerUpdate, PasswordChange, SectionAccessInput

cache = Redis.from_url(settings.redis_url, decode_responses=True, socket_connect_timeout=2, socket_timeout=2)


@asynccontextmanager
async def lifespan(app):
    settings.validate()
    task = None if os.environ.get('AIRLINK_TESTING') == 'true' else asyncio.create_task(payments.payment_worker())
    if os.environ.get('AIRLINK_TESTING') != 'true':
        customer_probe_service.start()
        customer_collector_service.start()
        system_stats_service.start()
    try:
        yield
    finally:
        customer_collector_service.stop()
        registration_username_service.stop()
        customer_probe_service.stop()
        system_stats_service.stop()
        if task:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task


app = FastAPI(title="AirLink ISP OS", version=__version__, lifespan=lifespan)
app.include_router(device_access.router)
app.include_router(online_device.router)
app.include_router(snmp_visibility.router)
app.include_router(device_login_profiles.router)
app.include_router(towers_device_access.router)
app.include_router(drive_backups.router)
app.include_router(sas4.router)
app.include_router(sas4_reports.router)
app.include_router(payments.router)
app.include_router(access_roles.router)


@app.middleware("http")
async def headers(request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@app.exception_handler(RequestValidationError)
async def safe_device_login_validation(request, exc):
    if request.url.path.startswith('/api/backups/google-drive'):
        return JSONResponse(status_code=422, content={'detail': 'Invalid Google Drive backup settings. Check the required fields.'},
                            headers={'Cache-Control': 'no-store'})
    if request.url.path.rstrip('/') == '/api/integrations/sas4/device-access':
        return JSONResponse(status_code=422, content={
            'detail': 'Invalid device login settings. Check the username, password and connection options.'},
            headers={'Cache-Control': 'no-store'})
    return await request_validation_exception_handler(request, exc)


@app.exception_handler(IntegrityError)
async def conflict(request, exc):
    from fastapi.responses import JSONResponse
    return JSONResponse(status_code=409, content={"detail": "Conflict: duplicate value or resource still has dependents"})


def limited(key, limit=8, seconds=300):
    try:
        count = cache.incr("rate:" + key)
        if count == 1:
            cache.expire("rate:" + key, seconds)
        if count > limit:
            raise HTTPException(429, "Too many attempts; wait five minutes")
    except RedisError:
        raise HTTPException(503, "Authentication rate limiter unavailable")


def public(obj):
    hidden = {"password_hash", "encrypted_credentials"}
    result = {c.name: getattr(obj, c.name) for c in obj.__table__.columns if c.name not in hidden}
    if isinstance(obj, User):
        result['show_snmp_profiles'] = snmp_visibility.visible(obj)
        if obj.role == 'owner':
            result['default_snmp_profile_visibility'] = snmp_visibility.new_account_default(obj)
        result['sections'] = section_access.effective(obj)
        result['editable_sections'] = section_access.editable(obj)
        result['deletable_sections'] = section_access.deletable(obj)
        result.update(access_roles.user_role(obj))
        result['place_ids'] = manager_places.public_places(obj)
        result.update(manager_parents.public_parent(obj))
    return result


def commit(db, user, action, target=None):
    audit(db, user, action, target)
    db.commit()


def get(db, model, key):
    obj = db.get(model, key)
    if obj is None:
        raise HTTPException(404, "Resource not found")
    return obj


def tower_ids(db, user):
    if user.role in ("owner", "viewer"):
        return select(Tower.id)
    if user.role == "manager":
        return manager_places.managed_towers(user.id)
    return select(Device.tower_id).join(DeviceAssignment, DeviceAssignment.device_id == Device.id).where(DeviceAssignment.user_id == user.id)


def devices_query(db, user):
    q = select(Device)
    if user.role == "technician":
        return q.join(DeviceAssignment, DeviceAssignment.device_id == Device.id).where(DeviceAssignment.user_id == user.id)
    return q.where(Device.tower_id.in_(tower_ids(db, user)))


def check_tower(db, user, tower_id, write=False):
    tower = get(db, Tower, tower_id)
    if write and user.role not in ("owner", "manager") and section_access.role_policy(user, db) is None:
        raise HTTPException(403, "Inventory write access required")
    if tower_id not in db.scalars(tower_ids(db, user)).all():
        raise HTTPException(404, "Resource not found")
    return tower


def check_device(db, user, device_id):
    obj = db.scalar(devices_query(db, user).where(Device.id == device_id))
    if not obj:
        raise HTTPException(404, "Resource not found")
    return obj


def refresh_cookie(response, value):
    response.set_cookie("airlink_refresh", value, httponly=True, secure=settings.secure_cookies,
                        samesite="strict", path="/api/auth", max_age=7 * 86400)


def session_response(db, user, response):
    session = LoginSession(user_id=user.id, expires_at=now() + timedelta(days=7))
    db.add(session)
    db.flush()
    refresh_cookie(response, issue_refresh(db, session))
    commit(db, user, "auth.login")
    return {"access_token": access_token(user, session), "expires_in": settings.access_seconds, "user": public(user)}


@app.get("/api/health")
def health(db=Depends(get_db)):
    try:
        db.execute(text("SELECT 1"))
        cache.ping()
    except Exception:
        raise HTTPException(503, "Database or Redis unavailable")
    return {"status": "ok", "version": __version__}


@app.get("/api/setup/status")
def setup_status(db=Depends(get_db)):
    return {"initialized": db.get(Initialization, 1) is not None}


@app.post("/api/setup", status_code=201)
def setup(data: Setup, request: Request, db=Depends(get_db)):
    limited("setup:" + request.client.host)
    if not settings.bootstrap_token or not secrets.compare_digest(data.token, settings.bootstrap_token):
        raise HTTPException(403, "Invalid local setup token")
    if db.get(Initialization, 1):
        raise HTTPException(409, "Owner already initialized")
    user = User(username=data.username, password_hash=hasher.hash(data.password), role="owner")
    db.add(user)
    db.flush()
    # Singleton primary key makes concurrent first-owner requests atomic.
    db.add(Initialization(id=1, owner_id=user.id))
    commit(db, user, "system.initialize")
    return public(user)


@app.post("/api/auth/login")
def login(data: Login, request: Request, response: Response, db=Depends(get_db)):
    limited("ip:" + request.client.host, 30)
    limited("user:" + digest(data.username.lower()), 10)
    user = db.scalar(select(User).where(User.username == data.username))
    valid = verify_password(data.password, user.password_hash if user else dummy_hash)
    if not valid or not user or not user.active:
        audit(db, None, "auth.failed")
        db.commit()
        raise HTTPException(401, "Invalid username or password")
    if hasher.check_needs_rehash(user.password_hash):
        user.password_hash = hasher.hash(data.password)
    return session_response(db, user, response)


@app.post("/api/auth/refresh")
def refresh(request: Request, response: Response, db=Depends(get_db)):
    if request.headers.get("X-AirLink-Request") != "1":
        raise HTTPException(403, "Same-origin request header required")
    raw = request.cookies.get("airlink_refresh", "")
    token = db.scalar(select(RefreshToken).where(RefreshToken.digest == digest(raw)).with_for_update())
    if not token:
        raise HTTPException(401, "Session expired")
    session = db.scalar(select(LoginSession).where(LoginSession.id == token.session_id).with_for_update())
    if token.consumed:
        session.revoked = True
        commit(db, None, "auth.refresh_reuse", session.id)
        raise HTTPException(401, "Refresh token reused; session revoked")
    user = get(db, User, session.user_id)
    if session.revoked or aware(session.expires_at) <= now() or not user.active:
        raise HTTPException(401, "Session expired")
    token.consumed = True
    refresh_cookie(response, issue_refresh(db, session))
    db.commit()
    return {"access_token": access_token(user, session), "expires_in": settings.access_seconds, "user": public(user)}


@app.post("/api/auth/logout")
def logout(request: Request, response: Response, credentials=Depends(bearer), user=Depends(current_user), db=Depends(get_db)):
    claims = jwt.decode(credentials.credentials, settings.secret, algorithms=["HS256"],
                        audience="airlink-dashboard", issuer="airlink")
    session = get(db, LoginSession, claims["sid"])
    session.revoked = True
    response.delete_cookie("airlink_refresh", path="/api/auth")
    commit(db, user, "auth.logout")
    return {"ok": True}


@app.get("/api/auth/me")
def me(user=Depends(current_user)):
    return public(user)


@app.put("/api/auth/password")
def change_password(data: PasswordChange, credentials=Depends(bearer), user=Depends(current_user), db=Depends(get_db)):
    limited("password-change:" + user.id, limit=8)
    if not verify_password(data.current_password, user.password_hash):
        raise HTTPException(403, "Current password is incorrect")
    claims = jwt.decode(credentials.credentials, settings.secret, algorithms=["HS256"],
                        audience="airlink-dashboard", issuer="airlink")
    user.password_hash = hasher.hash(data.new_password)
    db.execute(update(LoginSession).where(LoginSession.user_id == user.id,
        LoginSession.id != claims['sid']).values(revoked=True))
    commit(db, user, "auth.password_change", user.id)
    return {"ok": True}


@app.get("/api/users")
def users(user=Depends(owner), db=Depends(get_db)):
    return [public(x) for x in db.scalars(select(User).order_by(User.username))]


@app.post("/api/users", status_code=201)
def add_user(data: UserInput, user=Depends(owner), db=Depends(get_db)):
    manager_parents.lock(db)
    obj = User(username=data.username, password_hash=hasher.hash(data.password), role=data.role)
    db.add(obj)
    db.flush()
    manager_places.save(db, obj, data.place_ids)
    access_roles.assign_input(db, obj, data)
    manager_parents.save(db, obj, data)
    snmp_visibility.save(db, obj, data.show_snmp_profiles)
    commit(db, user, "user.create", obj.id)
    return public(obj)


@app.put("/api/users/{user_id}")
def edit_account(user_id: str, data: ManagerUpdate, user=Depends(owner), db=Depends(get_db)):
    manager_parents.lock(db)
    obj = get(db, User, user_id)
    if obj.role == "owner":
        raise HTTPException(409, "Owner accounts cannot be edited here")
    next_role = data.role or obj.role
    role_changed = next_role != obj.role
    changed = obj.username != data.username or data.password is not None or role_changed
    if role_changed:
        previous_role = obj.role
        if previous_role == 'manager':
            manager_parents.clear(db, obj.id)
            db.execute(update(Tower).where(Tower.manager_id == obj.id).values(manager_id=None))
            db.execute(delete(ManagerPlace).where(ManagerPlace.user_id == obj.id))
            db.execute(delete(UserManagerRole).where(UserManagerRole.user_id == obj.id))
            db.execute(delete(UserAccessRole).where(UserAccessRole.user_id == obj.id))
        if previous_role == 'technician':
            db.execute(delete(DeviceAssignment).where(DeviceAssignment.user_id == obj.id))
        obj.role = next_role
        audit(db, user, 'user.role_change', f'{obj.id}:{previous_role}->{next_role}')
    manager_places.save(db, obj, data.place_ids)
    access_roles.assign_input(db, obj, data)
    manager_parents.save(db, obj, data)
    snmp_visibility.save(db, obj, data.show_snmp_profiles)
    obj.username = data.username
    if data.password is not None:
        obj.password_hash = hasher.hash(data.password)
    if changed:
        db.execute(update(LoginSession).where(LoginSession.user_id == obj.id).values(revoked=True))
    commit(db, user, "user.update", obj.id)
    return public(obj)


@app.put("/api/users/{user_id}/sections")
def set_user_sections(user_id: str, data: SectionAccessInput, user=Depends(owner), db=Depends(get_db)):
    obj = get(db, User, user_id)
    if obj.role == 'owner':
        raise HTTPException(409, 'Owner accounts always have full access')
    if obj.role != 'manager':
        raise HTTPException(422, 'Section permissions apply to manager accounts')
    if section_access.role_policy(obj, db) is not None:
        raise HTTPException(409, 'This account uses a role. Edit its access group in Access Roles.')
    row = db.get(UserSectionAccess, obj.id)
    if row is None:
        row = UserSectionAccess(user_id=obj.id)
        db.add(row)
    row.sections = [key for key in section_access.ASSIGNABLE if key in data.sections]
    edits = db.get(UserSectionEdits, obj.id)
    if data.editable_sections is not None:
        if edits is None:
            edits = UserSectionEdits(user_id=obj.id)
            db.add(edits)
        edits.sections = [key for key in row.sections if key in data.editable_sections]
    elif edits is not None:
        edits.sections = [key for key in row.sections if key in edits.sections]
    deletes = db.get(UserSectionDeletes, obj.id)
    if data.deletable_sections is not None:
        if deletes is None:
            deletes = UserSectionDeletes(user_id=obj.id)
            db.add(deletes)
        deletes.sections = [key for key in row.sections if key in data.deletable_sections]
    elif deletes is not None:
        deletes.sections = [key for key in row.sections if key in deletes.sections]
    commit(db, user, 'user.sections', obj.id + ':view=' + ','.join(row.sections)
           + ';edit=' + ','.join(edits.sections if edits is not None else row.sections)
           + ';delete=' + ','.join(deletes.sections if deletes is not None else (edits.sections if edits is not None else row.sections)))
    return public(obj)


@app.delete("/api/users/{user_id}", status_code=204)
def delete_account(user_id: str, user=Depends(owner), db=Depends(get_db)):
    manager_parents.lock(db)
    obj = get(db, User, user_id)
    if obj.role == "owner":
        raise HTTPException(409, "Owner accounts cannot be deleted here")
    # Preserve inventory and audit history while removing credentials and sessions.
    db.execute(update(Tower).where(Tower.manager_id == obj.id).values(manager_id=None))
    db.execute(delete(DeviceAssignment).where(DeviceAssignment.user_id == obj.id))
    db.execute(delete(RefreshToken).where(RefreshToken.session_id.in_(
        select(LoginSession.id).where(LoginSession.user_id == obj.id))))
    db.execute(delete(LoginSession).where(LoginSession.user_id == obj.id))
    db.execute(update(AuditLog).where(AuditLog.user_id == obj.id).values(user_id=None))
    target = f"{obj.id}:{obj.username}"
    db.delete(obj)
    commit(db, user, "user.delete", target)


@app.post("/api/users/{user_id}/disable")
def disable_user(user_id: str, user=Depends(owner), db=Depends(get_db)):
    manager_parents.lock(db)
    obj = get(db, User, user_id)
    if obj.id == user.id or obj.role == "owner":
        raise HTTPException(409, "Cannot disable owner accounts")
    obj.active = False
    for session in db.scalars(select(LoginSession).where(LoginSession.user_id == obj.id)):
        session.revoked = True
    commit(db, user, "user.disable", obj.id)
    return public(obj)


@app.put("/api/users/{user_id}/devices/{device_id}")
def assign_device(user_id: str, device_id: str, user=Depends(owner), db=Depends(get_db)):
    technician = get(db, User, user_id)
    get(db, Device, device_id)
    if technician.role != "technician":
        raise HTTPException(422, "Device assignments apply to technicians")
    db.merge(DeviceAssignment(user_id=user_id, device_id=device_id))
    commit(db, user, "device.assign", device_id)
    return {"ok": True}


@app.get("/api/places")
def places(user=Depends(current_user), db=Depends(get_db)):
    counts = (select(TowerPlace.place_id, func.count().label('total'))
              .where(TowerPlace.tower_id.in_(tower_ids(db, user)))
              .group_by(TowerPlace.place_id).subquery())
    query = select(Place, counts.c.total).outerjoin(counts, counts.c.place_id == Place.id)
    if user.role == 'manager':
        query = query.where(or_(counts.c.total > 0, Place.id.in_(manager_places.assigned_places(user.id))))
    elif user.role not in ('owner', 'viewer'):
        query = query.where(counts.c.total > 0)
    return [{**public(place), 'tower_count': count or 0} for place, count in db.execute(query.order_by(Place.name))]


@app.post("/api/places", status_code=201)
def add_place(data: PlaceInput, user=Depends(owner), db=Depends(get_db)):
    obj = Place(name=data.name)
    db.add(obj)
    db.flush()
    commit(db, user, 'place.create', obj.id)
    return {**public(obj), 'tower_count': 0}


@app.put("/api/places/{place_id}")
def edit_place(place_id: str, data: PlaceInput, user=Depends(owner), db=Depends(get_db)):
    obj = get(db, Place, place_id)
    obj.name = data.name
    commit(db, user, 'place.update', obj.id)
    return public(obj)


@app.delete("/api/places/{place_id}", status_code=204)
def delete_place(place_id: str, user=Depends(owner), db=Depends(get_db)):
    obj = get(db, Place, place_id)
    if db.scalar(select(TowerPlace.tower_id).where(TowerPlace.place_id == place_id).limit(1)):
        raise HTTPException(409, 'Move or remove the towers in this place first')
    db.delete(obj)
    commit(db, user, 'place.delete', place_id)


def tower_place(db, tower_id):
    membership = db.get(TowerPlace, tower_id)
    return membership.place_id if membership else None


def save_tower_place(db, tower_id, data, user):
    if 'place_id' not in data.model_fields_set:
        return
    membership = db.get(TowerPlace, tower_id)
    previous = membership.place_id if membership else None
    if previous == data.place_id:
        return
    if user.role != 'owner':
        raise HTTPException(403, 'Only owner can move towers between places')
    if data.place_id:
        get(db, Place, data.place_id)
        if membership:
            membership.place_id = data.place_id
        else:
            db.add(TowerPlace(tower_id=tower_id, place_id=data.place_id))
    elif membership:
        db.delete(membership)


@app.get("/api/towers")
def towers(user=Depends(current_user), db=Depends(get_db)):
    result = []
    for tower in db.scalars(select(Tower).where(Tower.id.in_(tower_ids(db, user))).order_by(Tower.name)):
        item = {**public(tower), "place_id": tower_place(db, tower.id), **tower_api.public_settings(db, tower.id, user)}
        devices = db.scalars(devices_query(db, user).where(Device.tower_id == tower.id)).all()
        statuses = [effective_status(d) for d in devices]
        item.update(sector_count=db.scalar(select(func.count()).select_from(Sector).where(Sector.tower_id == tower.id)),
                    status="offline" if "offline" in statuses else "warning" if "unknown" in statuses else "online" if statuses else "unknown")
        result.append(item)
    return result


def manager_check(db, manager_id):
    if manager_id:
        manager = get(db, User, manager_id)
        if manager.role != "manager" or not manager.active:
            raise HTTPException(422, "Assigned user must be an active manager")


@app.post("/api/towers", status_code=201)
def add_tower(data: TowerInput, user=Depends(owner), db=Depends(get_db)):
    manager_check(db, data.manager_id)
    obj = Tower(**data.model_dump(exclude=tower_api.FIELDS | {"place_id"}))
    db.add(obj)
    db.flush()
    save_tower_place(db, obj.id, data, user)
    tower_api.save(db, obj.id, data, user)
    commit(db, user, "tower.create", obj.id)
    return {**public(obj), "place_id": tower_place(db, obj.id), **tower_api.public_settings(db, obj.id, user)}


@app.post("/api/towers/{tower_id}/discover")
def discover_tower(tower_id: str, data: DiscoveryInput, user=Depends(current_user), db=Depends(get_db)):
    tower = check_tower(db, user, tower_id, write=True)
    try:
        network = discovery.management_network(tower.management_ip, data.prefix)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    # One scan at a time per tower, including across API workers.
    try:
        lock = cache.lock("discovery:" + tower_id, timeout=60, blocking=False)
        if not lock.acquire(blocking=False):
            raise HTTPException(409, "Discovery is already running for this tower")
    except RedisError as exc:
        raise HTTPException(503, "Discovery coordination is unavailable") from exc
    try:
        commit(db, user, "tower.discover", f"{tower_id}:{network}")
        try:
            addresses = discovery.scan(network)
        except (RuntimeError, OSError) as exc:
            raise HTTPException(503, str(exc)) from exc
        existing = set(db.scalars(select(Device.ip_address).where(Device.ip_address.in_(addresses))))
        return {"network": str(network), "scanned": len(list(network.hosts())),
                "hosts": [{"ip_address": ip, "already_added": ip in existing} for ip in addresses]}
    finally:
        try:
            if lock.owned():
                lock.release()
        except RedisError:
            pass


@app.post('/api/towers/{tower_id}/discover-snmp')
def discover_tower_snmp(tower_id: str, data: SNMPDiscoveryInput, user=Depends(owner), db=Depends(get_db)):
    tower = check_tower(db, user, tower_id, write=True)
    try:
        network = discovery.management_network(tower.management_ip, data.prefix)
        profiles = snmp_discovery.candidates(db, data.profile_id)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    addresses = [str(address) for address in network.hosts()]
    batch = addresses[data.offset:data.offset + snmp_discovery.BATCH_SIZE]
    try:
        lock = cache.lock('discovery:' + tower_id, timeout=45, blocking=False)
        if not lock.acquire(blocking=False):
            raise HTTPException(409, 'Discovery is already running for this tower')
    except RedisError as exc:
        raise HTTPException(503, 'Discovery coordination is unavailable') from exc
    try:
        if data.offset == 0:
            commit(db, user, 'tower.discover_snmp', f'{tower_id}:{network}')
        hosts, timed_out = asyncio.run(snmp_discovery.scan_batch(batch, profiles))
        existing = {device.ip_address: device for device in db.scalars(select(Device).where(Device.ip_address.in_([h['ip_address'] for h in hosts])))}
        for host in hosts:
            device = existing.get(host['ip_address'])
            host['already_added'] = device is not None
            host['device_id'] = device.id if device else None
            host['device_tower_id'] = device.tower_id if device else None
            host['assigned_snmp_profile_id'] = device.snmp_profile_id if device else None
            host['snmp_applied'] = bool(device and host.get('snmp_profile_id') and device.snmp_profile_id == host['snmp_profile_id'])
        scanned = min(data.offset + len(batch), len(addresses))
        return {'network': str(network), 'scanned': scanned, 'total': len(addresses),
                'next_offset': scanned if scanned < len(addresses) else None,
                'hosts': hosts, 'timed_out': timed_out}
    finally:
        try:
            if lock.owned():
                lock.release()
        except RedisError:
            pass


@app.put("/api/towers/{tower_id}")
def edit_tower(tower_id: str, data: TowerInput, user=Depends(current_user), db=Depends(get_db)):
    obj = check_tower(db, user, tower_id, write=True)
    if 'manager_id' in data.model_fields_set:
        if user.role != "owner" and data.manager_id != obj.manager_id:
            raise HTTPException(403, "Only owner can reassign towers")
        manager_check(db, data.manager_id)
    save_tower_place(db, obj.id, data, user)
    tower_api.save(db, obj.id, data, user)
    excluded = tower_api.FIELDS | {"place_id"}
    if 'manager_id' not in data.model_fields_set:
        excluded = excluded | {'manager_id'}
    for key, value in data.model_dump(exclude=excluded).items():
        setattr(obj, key, value)
    commit(db, user, "tower.update", obj.id)
    return {**public(obj), "place_id": tower_place(db, obj.id), **tower_api.public_settings(db, obj.id, user)}


@app.delete("/api/towers/{tower_id}", status_code=204)
def delete_tower(tower_id: str, user=Depends(current_user), db=Depends(get_db)):
    obj = check_tower(db, user, tower_id, write=True)
    # Legacy managers keep their previous owner-only tower deletion restriction.
    if user.role != 'owner' and section_access.role_policy(user, db) is None:
        raise HTTPException(403, 'Owner or role delete access required')
    db.delete(obj)
    commit(db, user, "tower.delete", tower_id)


@app.get("/api/sectors")
def sectors(user=Depends(current_user), db=Depends(get_db)):
    q = select(Sector).where(Sector.tower_id.in_(tower_ids(db, user)))
    if user.role == "technician":
        q = q.where(Sector.id.in_(devices_query(db, user).with_only_columns(Device.sector_id)))
    return [public(x) for x in db.scalars(q.order_by(Sector.name))]


@app.post("/api/sectors", status_code=201)
def add_sector(data: SectorInput, user=Depends(current_user), db=Depends(get_db)):
    check_tower(db, user, data.tower_id, write=True)
    obj = Sector(**data.model_dump())
    db.add(obj)
    db.flush()
    commit(db, user, "sector.create", obj.id)
    return public(obj)


@app.put("/api/sectors/{sector_id}")
def edit_sector(sector_id: str, data: SectorInput, user=Depends(current_user), db=Depends(get_db)):
    obj = get(db, Sector, sector_id)
    check_tower(db, user, obj.tower_id, write=True)
    check_tower(db, user, data.tower_id, write=True)
    if obj.tower_id != data.tower_id and db.scalar(select(func.count()).select_from(Device).where(Device.sector_id == sector_id)):
        raise HTTPException(409, "Move sector devices first")
    for key, value in data.model_dump().items():
        setattr(obj, key, value)
    commit(db, user, "sector.update", obj.id)
    return public(obj)


@app.delete("/api/sectors/{sector_id}", status_code=204)
def delete_sector(sector_id: str, user=Depends(current_user), db=Depends(get_db)):
    obj = get(db, Sector, sector_id)
    check_tower(db, user, obj.tower_id, write=True)
    db.delete(obj)
    commit(db, user, "sector.delete", sector_id)


def effective_status(device):
    if not device.enabled or not device.last_poll or (now() - aware(device.last_poll)).total_seconds() > device.poll_interval * 3 + 30:
        return "unknown"
    return device.status


def snmp_status(device, metric):
    if not device.snmp_profile_id:
        return "not_configured"
    if not device.enabled:
        return "disabled"
    if not device.last_poll or not metric:
        return "pending"
    if (now() - aware(metric.collected_at)).total_seconds() > device.poll_interval * 3 + 30:
        return "stale"
    result = metric.values.get("snmp_up")
    return "connected" if result is True else "failed" if result is False else "pending"


@app.get("/api/devices")
def devices(user=Depends(current_user), db=Depends(get_db)):
    latest = (select(Metric.id).where(Metric.device_id == Device.id)
              .order_by(Metric.collected_at.desc(), Metric.id.desc()).limit(1).correlate(Device).scalar_subquery())
    query = devices_query(db, user).add_columns(Metric).outerjoin(Metric, Metric.id == latest).order_by(Device.name)
    result = []
    configs = {}
    for device, metric in db.execute(query):
        if device.tower_id not in configs:
            configs[device.tower_id] = tower_api.configuration(db, device.tower_id)['enabled']
        status = 'not_configured'
        fresh = bool(device.enabled and device.last_poll and metric and
                     (now() - aware(metric.collected_at)).total_seconds() <= device.poll_interval * 3 + 30)
        if configs[device.tower_id]:
            status = ('disabled' if not device.enabled else 'pending' if not device.last_poll or not metric
                      else 'stale' if not fresh else metric.values.get('api_status', 'pending'))
        values = metric.values if fresh else {}
        telemetry = {key: values[key] for key in ('cpu_percent', 'memory_percent', 'uptime_seconds',
            'ethernet_links', 'signal_dbm', 'weakest_signal_dbm', 'wireless_clients',
            'radio_frequencies_mhz', 'wireless_ssids', 'firmware_version', 'device_model', 'telemetry_source') if key in values}
        if not telemetry.get('ethernet_links'):
            telemetry['ethernet_links'] = [{'name': port.get('name', index), 'speed_mbps': port['speed_mbps']}
                for index, port in values.get('interfaces', {}).items()
                if port.get('type') == 6 and port.get('status') == 1 and port.get('speed_mbps', 0) > 0]
        detected = metric.values.get('detected_vendor') if metric and device.last_poll else None
        detected = detected if detected in VENDOR_LABELS and detected != 'generic' else None
        effective_vendor = device.vendor if device.vendor != 'generic' else detected or 'generic'
        device_status = effective_status(device)
        downtime = (max(0, int((now() - aware(device.down_since)).total_seconds()))
                    if device_status == 'offline' and device.down_since else None)
        result.append({**public(device), 'detected_vendor': detected,
                       'vendor_label': VENDOR_LABELS.get(effective_vendor, effective_vendor),
                       'vendor_auto': device.vendor == 'generic',
                       'status': device_status, 'downtime_seconds': downtime,
                       'snmp_status': snmp_status(device, metric),
                       'api_status': status, 'telemetry': telemetry,
                       'telemetry_at': metric.collected_at if fresh else None})
    return result


def device_validate(db, user, data, existing=None):
    check_tower(db, user, data.tower_id, write=True)
    if data.sector_id and get(db, Sector, data.sector_id).tower_id != data.tower_id:
        raise HTTPException(422, "Sector must belong to device tower")
    if user.role != "owner":
        expected = (existing.snmp_profile_id, existing.poll_interval, existing.connection_timeout, existing.retries, existing.failure_threshold, existing.cpu_threshold) if existing else (None, 60, 2, 2, 3, 90)
        if (data.snmp_profile_id, data.poll_interval, data.connection_timeout, data.retries, data.failure_threshold, data.cpu_threshold) != expected:
            raise HTTPException(403, "Only owner configures monitoring credentials and thresholds")
    if data.snmp_profile_id:
        get(db, SNMPProfile, data.snmp_profile_id)


@app.post("/api/devices", status_code=201)
def add_device(data: DeviceInput, user=Depends(current_user), db=Depends(get_db)):
    device_validate(db, user, data)
    obj = Device(**data.model_dump())
    db.add(obj)
    db.flush()
    commit(db, user, "device.create", obj.id)
    return public(obj)


@app.put("/api/devices/{device_id}")
def edit_device(device_id: str, data: DeviceInput, user=Depends(current_user), db=Depends(get_db)):
    obj = check_device(db, user, device_id)
    check_tower(db, user, obj.tower_id, write=True)
    device_validate(db, user, data, obj)
    if (obj.ip_address, obj.snmp_profile_id, obj.enabled, obj.tower_id, obj.vendor, obj.connection_timeout, obj.poll_interval, obj.retries) != (data.ip_address, data.snmp_profile_id, data.enabled, data.tower_id, data.vendor, data.connection_timeout, data.poll_interval, data.retries):
        obj.last_poll = None
        obj.status = "unknown"
        obj.failures = 0
        obj.down_since = None
    for key, value in data.model_dump().items():
        setattr(obj, key, value)
    commit(db, user, "device.update", obj.id)
    return public(obj)


@app.put('/api/devices/{device_id}/snmp-profile')
def assign_device_snmp(device_id: str, data: DeviceSNMPAssignment, user=Depends(owner), db=Depends(get_db)):
    obj = check_device(db, user, device_id)
    if obj.tower_id != data.tower_id or obj.ip_address != data.expected_ip_address:
        raise HTTPException(409, 'Device location or IP changed. Discover this tower again.')
    if obj.snmp_profile_id != data.previous_snmp_profile_id:
        raise HTTPException(409, 'Device SNMP profile changed. Discover this tower again.')
    get(db, SNMPProfile, data.snmp_profile_id)
    if obj.snmp_profile_id != data.snmp_profile_id:
        obj.snmp_profile_id = data.snmp_profile_id
        obj.last_poll = None
        obj.status = 'unknown'
        obj.failures = 0
        obj.down_since = None
    commit(db, user, 'device.snmp_profile.assign', obj.id)
    return {'id': obj.id, 'snmp_profile_id': obj.snmp_profile_id}


@app.delete("/api/devices/{device_id}", status_code=204)
def delete_device(device_id: str, user=Depends(current_user), db=Depends(get_db)):
    obj = check_device(db, user, device_id)
    check_tower(db, user, obj.tower_id, write=True)
    db.delete(obj)
    commit(db, user, "device.delete", device_id)


@app.post('/api/snmp-profiles/discovery-public')
def discovery_public_profile(data: SNMPPublicProfileInput, user=Depends(owner), db=Depends(get_db)):
    for profile in db.scalars(select(SNMPProfile)):
        try:
            credentials = json.loads(cipher().decrypt(profile.encrypted_credentials.encode()))
        except Exception:
            continue
        if credentials.get('version') == data.version and credentials.get('community') == 'public':
            return {**public(profile), 'version': data.version}
    profile = SNMPProfile(name=f'Discovery public v{data.version} {secrets.token_hex(3)}',
        encrypted_credentials=cipher().encrypt(json.dumps({'version':data.version, 'community':'public'}).encode()).decode())
    db.add(profile)
    db.flush()
    commit(db, user, 'snmp.create', profile.id)
    return {**public(profile), 'version': data.version}


@app.post('/api/snmp-profiles/discovery-match')
def discovery_matched_profile(data: SNMPDiscoveryProfileInput, user=Depends(owner), db=Depends(get_db)):
    source = get(db, SNMPProfile, data.source_profile_id)
    secret = json.loads(cipher().decrypt(source.encrypted_credentials.encode()))
    if secret.get('version') not in ('1', '2', '2c') or not secret.get('community'):
        raise HTTPException(422, 'A saved community profile is required')
    for profile in db.scalars(select(SNMPProfile)):
        credentials = json.loads(cipher().decrypt(profile.encrypted_credentials.encode()))
        if credentials.get('version') == data.version and credentials.get('community') == secret['community']:
            return {**public(profile), 'version': data.version}
    profile = SNMPProfile(name=f'{source.name[:70]} v{data.version} {secrets.token_hex(3)}',
        encrypted_credentials=cipher().encrypt(json.dumps({'version': data.version,
            'community': secret['community']}).encode()).decode())
    db.add(profile)
    db.flush()
    commit(db, user, 'snmp.create', profile.id)
    return {**public(profile), 'version': data.version}


@app.get("/api/snmp-profiles")
def profiles(user=Depends(current_user), db=Depends(get_db)):
    snmp_visibility.require(user, db)
    result = []
    for profile in db.scalars(select(SNMPProfile)):
        item = public(profile)
        try:
            item['version'] = json.loads(cipher().decrypt(profile.encrypted_credentials.encode())).get('version', '3')
        except Exception:
            item['version'] = 'unknown'
        result.append(item)
    return result


@app.post("/api/snmp-profiles", status_code=201)
def add_profile(data: ProfileInput, user=Depends(settings_access), db=Depends(get_db)):
    secret = cipher().encrypt(json.dumps(data.model_dump(exclude={"name"}, exclude_none=True)).encode()).decode()
    obj = SNMPProfile(name=data.name, encrypted_credentials=secret)
    db.add(obj)
    db.flush()
    commit(db, user, "snmp.create", obj.id)
    return {**public(obj), "version": data.version}


@app.get("/api/devices/{device_id}/metrics")
def metrics(device_id: str, hours: int = Query(24, ge=1, le=720), user=Depends(current_user), db=Depends(get_db)):
    check_device(db, user, device_id)
    rows = db.scalars(select(Metric).where(Metric.device_id == device_id, Metric.collected_at >= now() - timedelta(hours=hours))
                      .order_by(Metric.collected_at.desc()).limit(2000)).all()
    return [public(x) for x in reversed(rows)]


@app.get("/api/devices/{device_id}/outages")
def device_outages(device_id: str, limit: int = Query(100, ge=1, le=500), user=Depends(current_user), db=Depends(get_db)):
    check_device(db, user, device_id)
    rows = db.scalars(select(DeviceOutage).where(DeviceOutage.device_id == device_id)
                      .order_by(DeviceOutage.ended_at.desc(), DeviceOutage.id.desc()).limit(limit))
    return [{**public(row), 'duration_seconds': max(0, int((aware(row.ended_at) - aware(row.started_at)).total_seconds()))}
            for row in rows]


@app.get("/api/devices/{device_id}/interfaces")
def interfaces(device_id: str, user=Depends(current_user), db=Depends(get_db)):
    check_device(db, user, device_id)
    return [public(x) for x in db.scalars(select(Interface).where(Interface.device_id == device_id))]


def wireless_management_context(db, user, device_id):
    device = check_device(db, user, device_id)
    metric = db.scalar(select(Metric).where(Metric.device_id == device_id)
                      .order_by(Metric.collected_at.desc(), Metric.id.desc()).limit(1))
    vendor = device.vendor if device.vendor != 'generic' else (metric.values.get('detected_vendor', 'generic') if metric else 'generic')
    return device, metric, vendor


@app.get('/api/devices/{device_id}/ethernet-ports')
def device_ethernet_ports(device_id: str, user=Depends(current_user), db=Depends(get_db)):
    device, metric, vendor = wireless_management_context(db, user, device_id)
    status = snmp_status(device, metric)
    profile = db.get(SNMPProfile, device.snmp_profile_id) if device.snmp_profile_id else None
    version = json.loads(cipher().decrypt(profile.encrypted_credentials.encode())).get('version', '3') if profile else None
    supported = vendor in ('mikrotik', 'mikrotik_switch') and version in ('2', '2c')
    fresh = supported and status == 'connected'
    ports = []
    # Use the latest poll only: failed polls must not reuse old link states or rates.
    values = metric.values if metric and device.last_poll and supported else {}
    for index, port in sorted(values.get('interfaces', {}).items(), key=lambda item: int(item[0])):
        if port.get('type') != 6:
            continue  # IF-MIB Ethernet (including Ethernet SFP), not bridges/VLANs/radios.
        state = ('disabled' if port.get('admin_status') == 2 else
                 {1: 'connected', 2: 'disconnected', 3: 'testing', 5: 'dormant',
                  6: 'not_present', 7: 'lower_layer_down'}.get(port.get('status'), 'unknown')) if fresh else 'unknown'
        ports.append({'if_index': int(index), 'name': port.get('name', index), 'state': state,
                      'speed_mbps': port.get('speed_mbps') if fresh and state == 'connected' else None,
                      'rx_bps': port.get('rx_bps') if fresh else None,
                      'tx_bps': port.get('tx_bps') if fresh else None})
    return {'supported': supported, 'snmp_status': status,
            'collected_at': metric.collected_at if values else None,
            'poll_interval': device.poll_interval, 'ports': ports}


@app.get('/api/devices/{device_id}/wireless-settings')
def device_wireless_settings(device_id: str, user=Depends(current_user), db=Depends(get_db)):
    device, metric, vendor = wireless_management_context(db, user, device_id)
    if vendor != 'mikrotik':
        return {'supported': False, 'radios': [],
                'message': 'SSID editing for this vendor/firmware is not supported yet. Registered clients remain available.'}
    config = tower_api.configuration(db, device.tower_id)
    try:
        radios = device_management.run(device.ip_address, config)
    except device_management.ManagementError as exc:
        raise HTTPException(exc.status, str(exc)) from None
    return {'supported': True, 'radios': radios, 'message': None if radios else 'No supported wireless interfaces found.'}


@app.put('/api/devices/{device_id}/wireless-settings')
def set_device_wireless_settings(device_id: str, data: WirelessSSIDInput, user=Depends(current_user), db=Depends(get_db)):
    device, _, vendor = wireless_management_context(db, user, device_id)
    check_tower(db, user, device.tower_id, write=True)
    if vendor != 'mikrotik':
        raise HTTPException(422, 'SSID editing for this vendor/firmware is not supported yet')
    config = tower_api.configuration(db, device.tower_id)
    try:
        lock = cache.lock(f'wireless-settings:{device.id}', timeout=25, blocking_timeout=0)
        if not lock.acquire(blocking=False):
            raise HTTPException(409, 'Another wireless change is running')
    except RedisError:
        raise HTTPException(503, 'Device change coordination is unavailable') from None
    try:
        commit(db, user, 'device.ssid.change_requested', device.id)
        result = device_management.run(device.ip_address, config, data.model_dump())
        device.last_poll = None
        commit(db, user, 'device.ssid.' + result['status'], device.id)
        return result
    except device_management.ManagementError as exc:
        commit(db, user, 'device.ssid.change_failed_or_unknown', device.id)
        raise HTTPException(exc.status, str(exc)) from None
    finally:
        with suppress(Exception):
            lock.release()


@app.get('/api/devices/{device_id}/wireless-clients')
def wireless_clients(device_id: str, user=Depends(current_user), db=Depends(get_db)):
    device = check_device(db, user, device_id)
    metric = db.scalar(select(Metric).where(Metric.device_id == device_id)
                       .order_by(Metric.collected_at.desc(), Metric.id.desc()).limit(1))
    fresh = bool(device.enabled and device.last_poll and metric and
                 (now() - aware(metric.collected_at)).total_seconds() <= device.poll_interval * 3 + 30)
    values = metric.values if fresh else {}
    clients = public_clients(values.get('wireless_registrations'))
    lookup_status = 'not_needed'
    unmatched = [row for row in clients if not row.get('pppoe_username') and row.get('pppoe_username_status') != 'ambiguous']
    if unmatched:
        matches, lookup_status = registration_username_service.lookup(db, user)
        for row in unmatched:
            row['pppoe_username'] = matches.get(row['mac_address'])
            row['pppoe_username_status'] = ('matched' if row['pppoe_username'] else
                'ambiguous' if row['mac_address'] in matches else lookup_status if lookup_status == 'pending' else 'unavailable')
    total = values.get('wireless_clients')
    available = bool(clients) or (values.get('wireless_registration_source') and total == 0)
    return {'clients': clients, 'total': total, 'username_lookup_status': lookup_status, 'status': 'available' if available else
            'stale' if metric and not fresh else 'unavailable',
            'source': values.get('wireless_registration_source'),
            'collected_at': metric.collected_at if fresh else None}


@app.get("/api/alerts")
def alerts(user=Depends(current_user), db=Depends(get_db)):
    ids = devices_query(db, user).with_only_columns(Device.id)
    return [public(x) for x in db.scalars(select(Alert).where(Alert.device_id.in_(ids)).order_by(Alert.opened_at.desc()).limit(500))]


@app.post("/api/alerts/{alert_id}/acknowledge")
def acknowledge(alert_id: str, user=Depends(current_user), db=Depends(get_db)):
    if user.role == "viewer" and section_access.role_policy(user, db) is None:
        raise HTTPException(403, "Read-only account")
    obj = get(db, Alert, alert_id)
    check_device(db, user, obj.device_id)
    obj.acknowledged_by = user.id
    commit(db, user, "alert.acknowledge", alert_id)
    return public(obj)


def summary(db, user):
    inventory = db.scalars(devices_query(db, user)).all()
    ids = [d.id for d in inventory]
    online = sum(effective_status(d) == "online" for d in inventory)
    offline = sum(effective_status(d) == "offline" for d in inventory)
    # Aggregate in SQL: live clients must not load a day of metrics into memory.
    icmp = Metric.values['icmp_up'].as_boolean()
    sample_count, observations, successes = db.execute(select(func.count(Metric.id), func.count(icmp),
        func.sum(case((icmp.is_(True), 1), else_=0))).where(Metric.device_id.in_(ids),
        Metric.collected_at >= now() - timedelta(hours=24))).one()
    return {"towers": db.scalar(select(func.count()).select_from(Tower).where(Tower.id.in_(tower_ids(db, user)))),
            "sectors": len(sectors(user, db)), "devices": len(ids), "online": online, "offline": offline,
            "unknown": len(ids) - online - offline, "connected_clients": None,
            "active_alerts": db.scalar(select(func.count()).select_from(Alert).where(Alert.device_id.in_(ids), Alert.resolved_at.is_(None))),
            "availability_24h": round(100 * (successes or 0) / observations, 2) if observations else None,
            "sample_count": observations, "observed_at": now(), "system": system_stats_service.read()}


@app.get("/api/dashboard")
def dashboard(user=Depends(current_user), db=Depends(get_db)):
    return summary(db, user)


@app.get("/api/links")
def links(user=Depends(current_user), db=Depends(get_db)):
    ids = tower_ids(db, user)
    return [public(x) for x in db.scalars(select(NetworkLink).where(NetworkLink.source_id.in_(ids), NetworkLink.target_id.in_(ids)))]


@app.post("/api/links", status_code=201)
def add_link(data: LinkInput, user=Depends(owner), db=Depends(get_db)):
    get(db, Tower, data.source_id)
    get(db, Tower, data.target_id)
    if data.source_id == data.target_id:
        raise HTTPException(422, "A link needs two distinct towers")
    obj = NetworkLink(**data.model_dump(), verified_by=user.id)
    db.add(obj)
    db.flush()
    commit(db, user, "link.verify", obj.id)
    return public(obj)


@app.get("/api/reports/availability.csv")
def report(user=Depends(current_user), db=Depends(get_db)):
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["device_id", "device_name", "samples_24h", "availability_percent"])
    for device in db.scalars(devices_query(db, user)):
        rows = db.scalars(select(Metric).where(Metric.device_id == device.id, Metric.collected_at >= now() - timedelta(hours=24)))
        values = [m.values["icmp_up"] for m in rows if "icmp_up" in m.values]
        # Prevent formula execution in spreadsheets.
        name = "'" + device.name if device.name[:1] in "=+-@\t\r" else device.name
        writer.writerow([device.id, name, len(values), round(100 * sum(values) / len(values), 2) if values else ""])
    return Response(out.getvalue(), media_type="text/csv", headers={"Content-Disposition": "attachment; filename=airlink-availability.csv"})


@app.get("/api/audit")
def logs(user=Depends(settings_access), db=Depends(get_db)):
    return [public(x) for x in db.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(500))]


def broker(action, payload=None):
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
            sock.settimeout(180)
            sock.connect(settings.broker_socket)
            sock.sendall(json.dumps({"action": action, "payload": payload or {}}).encode() + b"\n")
            data = sock.makefile("rb").readline(1024 * 1024)
        result = json.loads(data)
        if not result.get("ok"):
            raise HTTPException(409, result.get("error", "System action rejected"))
        return result["result"]
    except (OSError, ValueError):
        raise HTTPException(503, "Local system controller unavailable")


@app.get("/api/system")
def system(user=Depends(settings_access)):
    return broker("status")


@app.get("/api/diagnostics")
def diagnostics(user=Depends(settings_access)):
    return broker("diagnostics.status")


@app.post("/api/system/restart", status_code=202)
def restart_system(payload: dict, user=Depends(updates_access), db=Depends(get_db)):
    if payload.get("confirm") is not True:
        raise HTTPException(422, "Confirm the system restart first")
    result = broker("system.restart", {"confirm": True})
    commit(db, user, "system.restart")
    return result


@app.get("/api/network")
def network(user=Depends(settings_access)):
    return broker("network.status")


@app.post("/api/network/{action}")
def network_action(action: str, payload: dict, user=Depends(settings_access), db=Depends(get_db)):
    if action not in {"save", "apply", "confirm", "restore", "test", "dns"}:
        raise HTTPException(404, "Unknown network action")
    result = broker("network." + action, payload)
    commit(db, user, "network." + action)
    return result


@app.get("/api/updates")
def updates(user=Depends(updates_access), db=Depends(get_db)):
    return {"current_version": __version__, "state": broker("updates.status"),
            "history": [public(x) for x in db.scalars(select(UpdateHistory).order_by(UpdateHistory.created_at.desc()).limit(100))]}


@app.post("/api/updates/{action}")
def update_action(action: str, payload: dict, user=Depends(updates_access), db=Depends(get_db)):
    if action not in {"check", "download", "verify", "install", "schedule"}:
        raise HTTPException(409, "Unsupported update action; rollback is disabled until validated")
    result = broker("updates." + action, payload)
    db.add(UpdateHistory(version=result.get("version", __version__), status=action, detail=json.dumps(result)))
    commit(db, user, "updates." + action)
    return result


@app.websocket("/api/ws")
async def live(websocket: WebSocket):
    await websocket.accept()
    try:
        message = await asyncio.wait_for(websocket.receive_json(), timeout=5)
        token = message.get("token", "")
        # Authentication is in the first frame, never in URL logs.
        while True:
            def read():
                with SessionLocal() as db:
                    user = resolve_user(token, db)
                    section_access.require_any(user, ("dashboard", "noc"), db)
                    return jsonable_encoder(summary(db, user))
            result = await asyncio.to_thread(read)
            await websocket.send_json(result)
            await asyncio.sleep(10)
    except (HTTPException, asyncio.TimeoutError, ValueError):
        await websocket.close(code=4401)
    except WebSocketDisconnect:
        pass


@app.websocket('/api/live')
async def live_changes(websocket: WebSocket):
    from . import live_updates
    await websocket.accept()
    try:
        message = await asyncio.wait_for(websocket.receive_json(), timeout=5)
        token = message.get('token', '')
        previous = None
        while True:
            # Reauthenticate and rescope every frame, including after grants change.
            current = await asyncio.to_thread(live_updates.snapshot, token)
            await websocket.send_json(live_updates.changes(previous, current))
            previous = current
            await asyncio.sleep(live_updates.INTERVAL)
    except (HTTPException, asyncio.TimeoutError, ValueError, TypeError, AttributeError):
        await websocket.close(code=4401)
    except WebSocketDisconnect:
        pass
