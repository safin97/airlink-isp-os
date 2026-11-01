import asyncio
import csv
import io
import json
import secrets
import socket
import jwt
from contextlib import asynccontextmanager
from datetime import timedelta
from typing import Optional
from fastapi import FastAPI, Depends, HTTPException, Request, Response, WebSocket, WebSocketDisconnect, Query
from fastapi.encoders import jsonable_encoder
from sqlalchemy import select, func, text, delete
from sqlalchemy.exc import IntegrityError
from redis import Redis
from redis.exceptions import RedisError
from . import __version__
from .config import settings
from .db import get_db, SessionLocal
from .models import (User, Role, Initialization, LoginSession, RefreshToken, Tower, Sector, Device,
                     DeviceAssignment, SNMPProfile, Metric, Alert, Interface, NetworkLink, UpdateHistory, AuditLog, now, audit)
from .security import (hasher, dummy_hash, verify_password, digest, aware, access_token, issue_refresh,
                       current_user, owner, resolve_user, cipher, bearer)
from .schemas import Login, Setup, UserInput, TowerInput, SectorInput, DeviceInput, ProfileInput, LinkInput

cache = Redis.from_url(settings.redis_url, decode_responses=True, socket_connect_timeout=2, socket_timeout=2)


@asynccontextmanager
async def lifespan(app):
    settings.validate()
    yield


app = FastAPI(title="AirLink ISP OS", version=__version__, lifespan=lifespan)


@app.middleware("http")
async def headers(request, call_next):
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


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
    return {c.name: getattr(obj, c.name) for c in obj.__table__.columns if c.name not in hidden}


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
        return select(Tower.id).where(Tower.manager_id == user.id)
    return select(Device.tower_id).join(DeviceAssignment, DeviceAssignment.device_id == Device.id).where(DeviceAssignment.user_id == user.id)


def devices_query(db, user):
    q = select(Device)
    if user.role == "technician":
        return q.join(DeviceAssignment, DeviceAssignment.device_id == Device.id).where(DeviceAssignment.user_id == user.id)
    return q.where(Device.tower_id.in_(tower_ids(db, user)))


def check_tower(db, user, tower_id, write=False):
    tower = get(db, Tower, tower_id)
    if write and user.role not in ("owner", "manager"):
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


@app.get("/api/users")
def users(user=Depends(owner), db=Depends(get_db)):
    return [public(x) for x in db.scalars(select(User).order_by(User.username))]


@app.post("/api/users", status_code=201)
def add_user(data: UserInput, user=Depends(owner), db=Depends(get_db)):
    obj = User(username=data.username, password_hash=hasher.hash(data.password), role=data.role)
    db.add(obj)
    db.flush()
    commit(db, user, "user.create", obj.id)
    return public(obj)


@app.post("/api/users/{user_id}/disable")
def disable_user(user_id: str, user=Depends(owner), db=Depends(get_db)):
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


@app.get("/api/towers")
def towers(user=Depends(current_user), db=Depends(get_db)):
    result = []
    for tower in db.scalars(select(Tower).where(Tower.id.in_(tower_ids(db, user))).order_by(Tower.name)):
        item = public(tower)
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
    obj = Tower(**data.model_dump())
    db.add(obj)
    db.flush()
    commit(db, user, "tower.create", obj.id)
    return public(obj)


@app.put("/api/towers/{tower_id}")
def edit_tower(tower_id: str, data: TowerInput, user=Depends(current_user), db=Depends(get_db)):
    obj = check_tower(db, user, tower_id, write=True)
    if user.role != "owner" and data.manager_id != obj.manager_id:
        raise HTTPException(403, "Only owner can reassign towers")
    manager_check(db, data.manager_id)
    for key, value in data.model_dump().items():
        setattr(obj, key, value)
    commit(db, user, "tower.update", obj.id)
    return public(obj)


@app.delete("/api/towers/{tower_id}", status_code=204)
def delete_tower(tower_id: str, user=Depends(owner), db=Depends(get_db)):
    db.delete(get(db, Tower, tower_id))
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


@app.get("/api/devices")
def devices(user=Depends(current_user), db=Depends(get_db)):
    return [{**public(x), "status": effective_status(x)} for x in db.scalars(devices_query(db, user).order_by(Device.name))]


def device_validate(db, user, data, existing=None):
    check_tower(db, user, data.tower_id, write=True)
    if data.sector_id and get(db, Sector, data.sector_id).tower_id != data.tower_id:
        raise HTTPException(422, "Sector must belong to device tower")
    if user.role != "owner":
        expected = (existing.snmp_profile_id, existing.poll_interval, existing.retries, existing.failure_threshold, existing.cpu_threshold) if existing else (None, 60, 2, 3, 90)
        if (data.snmp_profile_id, data.poll_interval, data.retries, data.failure_threshold, data.cpu_threshold) != expected:
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
    for key, value in data.model_dump().items():
        setattr(obj, key, value)
    commit(db, user, "device.update", obj.id)
    return public(obj)


@app.delete("/api/devices/{device_id}", status_code=204)
def delete_device(device_id: str, user=Depends(current_user), db=Depends(get_db)):
    obj = check_device(db, user, device_id)
    check_tower(db, user, obj.tower_id, write=True)
    db.delete(obj)
    commit(db, user, "device.delete", device_id)


@app.get("/api/snmp-profiles")
def profiles(user=Depends(owner), db=Depends(get_db)):
    return [public(x) for x in db.scalars(select(SNMPProfile))]


@app.post("/api/snmp-profiles", status_code=201)
def add_profile(data: ProfileInput, user=Depends(owner), db=Depends(get_db)):
    secret = cipher().encrypt(json.dumps(data.model_dump(exclude={"name"})).encode()).decode()
    obj = SNMPProfile(name=data.name, encrypted_credentials=secret)
    db.add(obj)
    db.flush()
    commit(db, user, "snmp.create", obj.id)
    return public(obj)


@app.get("/api/devices/{device_id}/metrics")
def metrics(device_id: str, hours: int = Query(24, ge=1, le=720), user=Depends(current_user), db=Depends(get_db)):
    check_device(db, user, device_id)
    rows = db.scalars(select(Metric).where(Metric.device_id == device_id, Metric.collected_at >= now() - timedelta(hours=hours))
                      .order_by(Metric.collected_at.desc()).limit(2000)).all()
    return [public(x) for x in reversed(rows)]


@app.get("/api/devices/{device_id}/interfaces")
def interfaces(device_id: str, user=Depends(current_user), db=Depends(get_db)):
    check_device(db, user, device_id)
    return [public(x) for x in db.scalars(select(Interface).where(Interface.device_id == device_id))]


@app.get("/api/alerts")
def alerts(user=Depends(current_user), db=Depends(get_db)):
    ids = devices_query(db, user).with_only_columns(Device.id)
    return [public(x) for x in db.scalars(select(Alert).where(Alert.device_id.in_(ids)).order_by(Alert.opened_at.desc()).limit(500))]


@app.post("/api/alerts/{alert_id}/acknowledge")
def acknowledge(alert_id: str, user=Depends(current_user), db=Depends(get_db)):
    if user.role == "viewer":
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
    samples = db.scalars(select(Metric).where(Metric.device_id.in_(ids), Metric.collected_at >= now() - timedelta(hours=24))).all()
    availability = [m.values["icmp_up"] for m in samples if "icmp_up" in m.values]
    return {"towers": db.scalar(select(func.count()).select_from(Tower).where(Tower.id.in_(tower_ids(db, user)))),
            "sectors": len(sectors(user, db)), "devices": len(ids), "online": online, "offline": offline,
            "unknown": len(ids) - online - offline, "connected_clients": None,
            "active_alerts": db.scalar(select(func.count()).select_from(Alert).where(Alert.device_id.in_(ids), Alert.resolved_at.is_(None))),
            "availability_24h": round(100 * sum(availability) / len(availability), 2) if availability else None,
            "sample_count": len(availability), "observed_at": now()}


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
def logs(user=Depends(owner), db=Depends(get_db)):
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
def system(user=Depends(owner)):
    return broker("status")


@app.post("/api/system/restart", status_code=202)
def restart_system(payload: dict, user=Depends(owner), db=Depends(get_db)):
    if payload.get("confirm") is not True:
        raise HTTPException(422, "Confirm the system restart first")
    result = broker("system.restart", {"confirm": True})
    commit(db, user, "system.restart")
    return result


@app.get("/api/network")
def network(user=Depends(owner)):
    return broker("network.status")


@app.post("/api/network/{action}")
def network_action(action: str, payload: dict, user=Depends(owner), db=Depends(get_db)):
    if action not in {"save", "apply", "confirm", "restore", "test", "dns"}:
        raise HTTPException(404, "Unknown network action")
    result = broker("network." + action, payload)
    commit(db, user, "network." + action)
    return result


@app.get("/api/updates")
def updates(user=Depends(owner), db=Depends(get_db)):
    return {"current_version": __version__, "state": broker("updates.status"),
            "history": [public(x) for x in db.scalars(select(UpdateHistory).order_by(UpdateHistory.created_at.desc()).limit(100))]}


@app.post("/api/updates/{action}")
def update_action(action: str, payload: dict, user=Depends(owner), db=Depends(get_db)):
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
                    return jsonable_encoder(summary(db, user))
            result = await asyncio.to_thread(read)
            await websocket.send_json(result)
            await asyncio.sleep(10)
    except (HTTPException, asyncio.TimeoutError, ValueError):
        await websocket.close(code=4401)
    except WebSocketDisconnect:
        pass
