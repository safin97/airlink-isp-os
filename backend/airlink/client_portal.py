"""Customer-only recharge portal. Never exposes staff sessions or router credentials."""
import ipaddress
import json
import secrets
import uuid
from typing import Optional
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from fastapi import APIRouter, Depends, HTTPException, Request, Response, Query
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator
from sqlalchemy import select, delete
from redis.exceptions import RedisError
from cryptography.fernet import InvalidToken
from . import sas4, payments
from .config import settings
from .db import get_db
from .models import ClientPortalSettings, ClientPortalSession, User, SAS4UserConnection, RechargePayment, now, uid, audit
from .security import owner, cipher, digest, aware

router = APIRouter(prefix='/api/client', tags=['Client portal'])
settings_router = APIRouter(prefix='/api/client-portal', tags=['Client portal settings'])
COOKIE = 'airlink_client'
UCP_PATH = '/user/api/index.php/api/'


class PortalSettingsInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    enabled: bool
    subscriber_networks: list[str] = Field(default_factory=list, max_length=32)

    @field_validator('subscriber_networks')
    @classmethod
    def networks(cls, values):
        result = []
        for value in values:
            network = ipaddress.ip_network(value.strip(), strict=True)
            if network.prefixlen == 0 or network.is_loopback or network.is_multicast or network.is_link_local:
                raise ValueError('Use dedicated PPPoE subscriber ranges, not shared NAT or proxy addresses')
            result.append(str(network))
        return list(dict.fromkeys(result))


@settings_router.get('')
def get_settings(actor=Depends(owner), db=Depends(get_db)):
    row = db.get(ClientPortalSettings, 1)
    return {'enabled': bool(row and row.enabled), 'subscriber_networks': row.subscriber_networks if row else [],
            'configured_by_you': bool(row and row.owner_id == actor.id), 'path': '/client'}


@settings_router.put('')
def save_settings(data: PortalSettingsInput, actor=Depends(owner), db=Depends(get_db)):
    connection, _ = sas4.local_user_connection(db, actor)
    row = db.get(ClientPortalSettings, 1)
    if row is None:
        row = ClientPortalSettings(id=1)
        db.add(row)
    row.owner_id, row.sas4_username = actor.id, connection.username
    row.enabled, row.subscriber_networks, row.version = data.enabled, data.subscriber_networks, uid()
    db.execute(delete(ClientPortalSession))
    audit(db, actor, 'client_portal.configure')
    db.commit()
    return get_settings(actor, db)


def configured(db):
    row = db.get(ClientPortalSettings, 1)
    if not row or not row.enabled:
        raise HTTPException(503, 'Client recharge is not available yet. Contact your internet provider.')
    actor = db.get(User, row.owner_id)
    connection = db.get(SAS4UserConnection, row.owner_id)
    if not actor or not actor.active or actor.role != 'owner' or not connection or connection.username != row.sas4_username:
        raise HTTPException(503, 'Client recharge is temporarily unavailable. Contact your internet provider.')
    return row, actor


def request_guard(request):
    # JSON plus this header makes cross-origin browser writes preflight; CORS is not enabled.
    if request.headers.get('X-AirLink-Request') != '1':
        raise HTTPException(403, 'Same-origin request required')
    origin = request.headers.get('origin')
    if origin:
        from urllib.parse import urlsplit
        parsed = urlsplit(origin)
        if parsed.scheme not in ('https', 'http') or parsed.netloc != request.headers.get('host'):
            raise HTTPException(403, 'Same-origin request required')


def peer_ip(request):
    # Use the ASGI peer only. Do not trust forwarded headers supplied by browsers.
    # Production Nginx overwrites XFF; Uvicorn trusts only that loopback proxy.
    try:
        return ipaddress.ip_address(request.client.host)
    except ValueError:
        return None


def rate(request, action, username=None):
    from .api import limited
    limited('client:' + action + ':' + str(peer_ip(request)), 30 if action == 'read' else 15)
    if username:
        limited('client:username:' + digest(username.casefold()), 10)


def ucp(client, route, token=None, body=None):
    headers = {'Authorization': 'Bearer ' + token} if token else {}
    url = sas4.DEFAULT_SERVER + UCP_PATH + route
    response = client.get(url, headers=headers) if body is None else client.post(url, headers=headers, json=sas4.wire_payload(body))
    data = sas4.response_json(response)
    if data.get('status') not in (200, '200'):
        raise sas4.SAS4Error('SAS4 customer authentication failed')
    return data


def validate_customer(db, actor, customer_id, username):
    connection, password = sas4.local_user_connection(db, actor)
    with sas4.sas4_session(connection, password) as (client, headers):
        record = sas4.raw_user(client, headers, customer_id)
    if record.get('username') != username or sas4.flag(record.get('enabled')) is not True:
        raise HTTPException(401, 'Your account is unavailable. Contact your internet provider.')
    return record


def automatic_identity(db, actor, ip, diagnostics=None):
    """Require one exact, fresh session; diagnostics never include customer identity."""
    def reject(reason):
        if diagnostics is not None:
            diagnostics['reason'] = reason
        return None

    connection, password = sas4.local_user_connection(db, actor)
    matches = []
    with sas4.sas4_session(connection, password) as (client, headers):
        for page in range(1, 6):
            result = sas4.response_json(client.post(sas4.DEFAULT_SERVER + sas4.API_PATH + 'index/online', headers=headers,
                json=sas4.wire_payload({'page': page, 'count': 100, 'sortBy': 'username', 'direction': 'asc', 'search': str(ip)})))
            rows = result.get('data')
            if not isinstance(rows, list) or len(rows) > 100 or any(not isinstance(row, dict) for row in rows):
                return reject('accounting_unavailable')
            try:
                total, size = int(result['total']), int(result.get('per_page', 100))
                if total < len(rows) or not 1 <= size <= 100 or len(rows) > size or int(result.get('current_page', page)) != page:
                    return reject('accounting_unavailable')
            except (KeyError, ValueError, TypeError, OverflowError):
                return reject('accounting_unavailable')
            for row in rows:
                try:
                    if ipaddress.ip_address(row.get('framedipaddress')) == ip:
                        matches.append(row)
                except (TypeError, ValueError):
                    continue
            if total <= page * size:
                break
            if not rows:
                return reject('accounting_unavailable')
        else:
            return reject('accounting_unavailable')
    if not matches:
        return reject('session_not_found')
    if len(matches) != 1:
        return reject('ambiguous_session')
    row = matches[0]
    if row.get('acctstoptime') not in (None, ''):
        return reject('session_not_found')
    try:
        raw_started = row['acctstarttime']
        started = datetime.fromisoformat(raw_started[:-1] + '+00:00' if raw_started.endswith('Z') else raw_started)
        if started.tzinfo is None:
            started = started.replace(tzinfo=ZoneInfo('Asia/Baghdad'))
        duration = int(row['acctsessiontime'])
        if duration < 0 or isinstance(row['acctsessiontime'], bool):
            return reject('accounting_unavailable')
        age = (now() - (started + timedelta(seconds=duration))).total_seconds()
        customer_id = int(row['user_details']['id'])
        username = row['username']
        if customer_id < 1 or not isinstance(username, str) or not username:
            return reject('accounting_unavailable')
        if age < 0:
            return reject('accounting_clock_mismatch')
        if age > 120:
            return reject('stale_session')
        return customer_id, username
    except (ValueError, TypeError, KeyError, OverflowError, AttributeError):
        return reject('accounting_unavailable')


class CustomerLogin(BaseModel):
    model_config = ConfigDict(extra='forbid')
    username: str = Field(min_length=1, max_length=128)
    password: SecretStr = Field(min_length=1, max_length=1024)
    challenge_id: str = Field(pattern=r'^[a-f0-9-]{36}$')
    captcha_text: str = Field(default='', max_length=100)


@router.get('/login-options')
def login_options(request: Request, db=Depends(get_db)):
    rate(request, 'options')
    config, _ = configured(db)
    challenge = str(uuid.uuid4())
    from .api import cache
    try:
        with sas4.httpx.Client(timeout=15, follow_redirects=False, trust_env=False) as remote:
            options = ucp(remote, 'resources/config')['data']
            required = sas4.flag(options.get('requires_captcha')) is True
            captcha = ucp(remote, 'login/captcha/' + challenge)['data'] if required else None
        if captcha is not None and (not isinstance(captcha, str) or len(captcha) > 300000 or not captcha.startswith('data:image/')):
            raise sas4.SAS4Error('Invalid CAPTCHA')
        cache.set('client:challenge:' + challenge, config.version, ex=300)
    except (sas4.SAS4Error, sas4.httpx.HTTPError, RedisError):
        raise HTTPException(503, 'Customer sign-in is temporarily unavailable. Please try again.') from None
    return {'challenge_id': challenge, 'captcha_image': captcha, 'auto_login': bool(config.subscriber_networks)}


def create_session(db, config, customer_id, username, response, token=None, ip=None):
    value = secrets.token_urlsafe(48)
    seconds = 7 * 86400 if token else 1800
    db.execute(delete(ClientPortalSession).where(ClientPortalSession.expires_at <= now()))
    db.add(ClientPortalSession(digest=digest(value), owner_id=config.owner_id, config_version=config.version,
        customer_id=customer_id, username=username, source_ip=str(ip) if ip else None,
        encrypted_token=cipher().encrypt(token.encode()).decode() if token else None,
        expires_at=now() + timedelta(seconds=seconds)))
    db.commit()
    response.set_cookie(COOKIE, value, httponly=True, secure=settings.secure_cookies, samesite='strict', path='/api/client', max_age=seconds)
    return {'authenticated': True}


@router.post('/login')
def login(data: CustomerLogin, request: Request, response: Response, db=Depends(get_db)):
    request_guard(request)
    rate(request, 'login', data.username)
    config, actor = configured(db)
    from .api import cache
    try:
        if cache.getdel('client:challenge:' + data.challenge_id) != config.version:
            raise HTTPException(401, 'Sign-in expired. Refresh and try again.')
        with sas4.httpx.Client(timeout=15, follow_redirects=False, trust_env=False) as remote:
            result = ucp(remote, 'auth/login', body={'username': data.username, 'password': data.password.get_secret_value(),
                'language': 'en', 'session_id': data.challenge_id, 'captcha_text': data.captcha_text or None})
            token = result.get('token')
            if not isinstance(token, str) or not 1 <= len(token) <= 16384:
                raise sas4.SAS4Error('Missing customer token')
            identity = ucp(remote, 'user', token)['data']
            customer_id, username = int(identity['id']), identity['username']
        validate_customer(db, actor, customer_id, username)
    except (sas4.SAS4Error, sas4.httpx.HTTPError, ValueError, TypeError, KeyError):
        raise HTTPException(401, 'Invalid username, password or verification code.') from None
    except RedisError:
        raise HTTPException(503, 'Sign-in is temporarily unavailable.') from None
    return create_session(db, config, customer_id, username, response, token=token)


@router.post('/auto-login')
def auto_login(request: Request, response: Response, db=Depends(get_db)):
    request_guard(request)
    rate(request, 'auto')
    config, actor = configured(db)
    ip = peer_ip(request)

    def unavailable(reason):
        return {'authenticated': False, 'reason': reason, 'source_ip': str(ip) if ip else None}

    if not ip or ip.is_loopback:
        return unavailable('local_connection')
    if not config.subscriber_networks:
        return unavailable('auto_login_disabled')
    if not any(ip in ipaddress.ip_network(net) for net in config.subscriber_networks):
        return unavailable('outside_subscriber_ranges')
    try:
        diagnostics = {}
        identity = automatic_identity(db, actor, ip, diagnostics=diagnostics)
        if not identity:
            return unavailable(diagnostics.get('reason', 'session_not_found'))
        validate_customer(db, actor, *identity)
    except HTTPException as exc:
        return unavailable('account_unavailable' if exc.status_code == 401 else 'verification_unavailable')
    except (sas4.SAS4Error, sas4.httpx.HTTPError):
        return unavailable('verification_unavailable')
    return create_session(db, config, *identity, response, ip=ip)


def current(request: Request, db=Depends(get_db)):
    config, actor = configured(db)
    session = db.get(ClientPortalSession, digest(request.cookies.get(COOKIE, '')))
    if (not session or session.owner_id != config.owner_id or session.config_version != config.version
            or aware(session.expires_at) <= now()):
        raise HTTPException(401, 'Please sign in to your client account.')
    from .api import limited
    limited('client:session:' + session.digest, 180)
    try:
        if session.encrypted_token:
            with sas4.httpx.Client(timeout=15, follow_redirects=False, trust_env=False) as remote:
                data = ucp(remote, 'user', cipher().decrypt(session.encrypted_token.encode()).decode())
            if int(data['data']['id']) != session.customer_id or data['data']['username'] != session.username:
                raise ValueError()
            can_recharge = 'prm_ucp_activate' in (data.get('permissions') or [])
        else:
            ip = peer_ip(request)
            if str(ip) != session.source_ip or automatic_identity(db, actor, ip) != (session.customer_id, session.username):
                raise ValueError()
            can_recharge = True
        record = validate_customer(db, actor, session.customer_id, session.username)
    except (sas4.SAS4Error, sas4.httpx.HTTPError, ValueError, TypeError, KeyError, InvalidToken):
        raise HTTPException(401, 'Your session expired. Please sign in again.') from None
    return config, actor, session, record, can_recharge


@router.post('/logout')
def logout(request: Request, response: Response, db=Depends(get_db)):
    request_guard(request)
    db.execute(delete(ClientPortalSession).where(ClientPortalSession.digest == digest(request.cookies.get(COOKIE, ''))))
    db.commit()
    response.delete_cookie(COOKIE, path='/api/client')
    return {'ok': True}


def account_data(context, db):
    _, actor, session, record, can_recharge = context
    connection, password = sas4.local_user_connection(db, actor)
    quote = sas4.fetch_recharge(connection, password, session.customer_id)
    methods = payments.payment_methods(actor, db)
    return {'username': session.username, 'profile': quote.get('profile'), 'expiration': quote.get('expiration'),
            'first_name': record.get('firstname'), 'last_name': record.get('lastname'), 'phone': record.get('phone'),
            'recharge_cost': quote.get('customer_price'), 'currency': quote.get('currency'),
            'can_recharge': can_recharge and quote['methods'].get('card') is True,
            'fib_configured': any(row['provider'] == 'fib' and row['configured'] for row in methods),
            'transaction_id': quote['transaction_id'], 'profile_id': quote['profile_id'],
            'payments': payments.user_payments(session.customer_id, actor, db)}


@router.get('/account')
def account(context=Depends(current), db=Depends(get_db)):
    try:
        return account_data(context, db)
    except sas4.SAS4Error:
        raise HTTPException(502, 'Your service details could not be loaded. Please try again.') from None


@router.get('/connection')
def connection_status(context=Depends(current), db=Depends(get_db)):
    from .online_sessions import service as sessions
    from .customer_probes import service as probes
    _, actor, session, _, _ = context
    snapshot = sessions.snapshot(db, actor)
    result = {'online': None, 'signal_dbm': None, 'status': 'unavailable', 'collected_at': None}
    if not snapshot or snapshot['collection_status'] != 'available':
        return result
    rows = [row for row in snapshot['clients'] if str(row.get('id')) == str(session.customer_id)
            and row.get('username') == session.username]
    if not rows:
        return {**result, 'online': False, 'status': 'offline'}
    if len(rows) != 1:
        return {**result, 'online': True, 'status': 'ambiguous'}
    if sum(row.get('ip_address') == rows[0].get('ip_address') for row in snapshot['clients']) != 1:
        return {**result, 'online': True, 'status': 'ambiguous'}
    # Only the session-owned subscriber can be probed; no address comes from the caller.
    probes.enrich(db, actor, {'clients': rows})
    row = rows[0]
    result.update(online=True, status=row.get('telemetry_status', 'unavailable'))
    signal = row.get('signal_dbm')
    try:
        age = (now() - aware(datetime.fromisoformat(row['telemetry_collected_at']))).total_seconds()
        fresh = 0 <= age <= 90 and 'signal_dbm' not in row.get('telemetry_stale_fields', [])
    except (KeyError, TypeError, ValueError):
        fresh = False
    if (fresh and isinstance(signal, (int, float)) and not isinstance(signal, bool)
            and -130 <= signal < 0):
        result.update(signal_dbm=signal, status='available', collected_at=row['telemetry_collected_at'])
    return result


def write_access(request, context):
    request_guard(request)
    rate(request, 'recharge')
    if not context[4]:
        raise HTTPException(403, 'Self-service recharge is not enabled for this account.')


class PinRecharge(BaseModel):
    model_config = ConfigDict(extra='forbid')
    pin: SecretStr = Field(min_length=1, max_length=128)
    transaction_id: str = Field(pattern=r'^[a-f0-9]{32}$')
    expected_profile_id: int = Field(ge=1)
    expected_expiration: Optional[str] = Field(default=None, max_length=80)


@router.post('/recharge')
def recharge(data: PinRecharge, request: Request, context=Depends(current), db=Depends(get_db)):
    write_access(request, context)
    _, actor, session, _, _ = context
    outstanding = db.scalar(select(RechargePayment).where(RechargePayment.user_id == actor.id,
        RechargePayment.sas4_user_id == session.customer_id,
        RechargePayment.status.in_(['creating', 'pending', 'activating', 'paid_review', 'creation_unknown', 'review_required'])))
    if outstanding:
        raise HTTPException(409, 'An existing payment needs to finish or be reviewed before another recharge.')
    result = sas4.recharge_user_card(session.customer_id, sas4.CardRecharge(method='card', pin=data.pin.get_secret_value(),
        transaction_id=data.transaction_id, expected_profile_id=data.expected_profile_id,
        expected_expiration=data.expected_expiration), actor, db)
    return {'recharged': result.get('recharged') is True}


@router.get('/fib-quote')
def fib_quote(package_profile_id: Optional[int] = Query(default=None, ge=1), context=Depends(current), db=Depends(get_db)):
    if not context[4]:
        raise HTTPException(403, 'Self-service recharge is not enabled for this account.')
    if package_profile_id is not None:
        from .client_packages import quote
        return quote(context[2].customer_id, package_profile_id, context[1], db)
    return payments.radius_card_quote(context[2].customer_id, context[1], db)


@router.get('/cards')
def cards_catalog(request: Request, context=Depends(current), db=Depends(get_db)):
    from .client_catalog import fetch_catalog
    rate(request, 'catalog')
    connection, password = sas4.local_user_connection(db, context[1])
    try:
        return fetch_catalog(connection, password)
    except (sas4.SAS4Error, sas4.httpx.HTTPError):
        raise HTTPException(502, 'Cards could not be synced from SAS4. Please try again.') from None


class FibCheckout(BaseModel):
    package_profile_id: Optional[int] = Field(default=None, ge=1)
    model_config = ConfigDict(extra='forbid')
    transaction_id: str = Field(pattern=r'^[a-f0-9]{32}$')
    expected_amount: str = Field(max_length=40)
    expected_profile_id: int = Field(ge=1)
    expected_expiration: Optional[str] = Field(default=None, max_length=80)
    radius_card_id: int = Field(ge=1)
    radius_series: str = Field(min_length=1, max_length=128, pattern=r'^[A-Za-z0-9_-]+$')


@router.post('/payments')
def checkout(data: FibCheckout, request: Request, context=Depends(current), db=Depends(get_db)):
    write_access(request, context)
    payment = payments.PaymentInput(provider='fib', card_source='radius_pin', **data.model_dump(exclude={'package_profile_id'}))
    if data.package_profile_id is not None:
        return payments.begin_customer_payment(context[2].customer_id, payment, context[1], db, package_profile_id=data.package_profile_id)
    return payments.begin_payment(context[2].customer_id, payment, context[1], db)


@router.get('/payments')
def history(context=Depends(current), db=Depends(get_db)):
    return payments.user_payments(context[2].customer_id, context[1], db)


@router.get('/payments/{order_id}')
def payment_status(order_id: str, context=Depends(current), db=Depends(get_db)):
    row = db.get(RechargePayment, order_id)
    if not row or row.user_id != context[1].id or row.sas4_user_id != context[2].customer_id:
        raise HTTPException(404, 'Payment not found')
    return payments.public_order(row)
