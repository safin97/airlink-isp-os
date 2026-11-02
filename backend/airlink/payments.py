"""Provider-verified IQD payments. Only explicit checkout requests create payments.
FIB: https://fib.iq/integrations/web-payments/
FastPay QR/validation: https://developer.fast-pay.iq/qr-integration
"""
import asyncio
import json
import re
from datetime import timedelta
from typing import Literal, Optional
from urllib.parse import urlparse
import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from . import sas4
from .db import get_db, SessionLocal
from .models import PaymentGateway, RechargePayment, SAS4UserConnection, User, now, audit
from .security import cipher, aware

router = APIRouter(prefix='/api/payments', tags=['Payments'])
Provider = Literal['fib', 'fastpay']
Environment = Literal['sandbox', 'production']
BASES = {
    ('fib', 'sandbox'): 'https://fib.stage.fib.iq', ('fib', 'production'): 'https://fib.prod.fib.iq',
    ('fastpay', 'sandbox'): 'https://staging-qr.fast-pay.iq', ('fastpay', 'production'): 'https://qr.fast-pay.iq',
}


class PaymentError(Exception):
    pass


class GatewayInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    environment: Environment = 'sandbox'
    merchant_id: str = Field(min_length=1, max_length=255)
    secret: Optional[str] = Field(default=None, max_length=2048)


class PaymentInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    provider: Provider
    transaction_id: str = Field(pattern=r'^[a-f0-9]{32}$')
    expected_amount: str = Field(max_length=40)
    expected_cost: str = Field(max_length=40)
    expected_profile_id: int = Field(ge=1)
    expected_expiration: Optional[str] = Field(default=None, max_length=80)


def decoded(secret):
    try:
        return json.loads(cipher().decrypt(secret.encode()).decode())
    except Exception as exc:
        raise PaymentError('Merchant credentials cannot be read. Save them again in My account.') from exc


def gateway_status(config):
    return {'provider': config.provider, 'environment': config.environment, 'configured': True,
            'merchant_id': decoded(config.encrypted_credentials)['merchant_id'], 'has_secret': True}


@router.get('/gateways')
def gateways(user=Depends(sas4.sas4_access), db=Depends(get_db)):
    configs = {c.provider: c for c in db.scalars(select(PaymentGateway).where(PaymentGateway.user_id == user.id))}
    return [gateway_status(configs[p]) if p in configs else {'provider': p, 'configured': False, 'environment': 'sandbox', 'merchant_id': '', 'has_secret': False} for p in ('fib', 'fastpay')]


@router.put('/gateways/{provider}')
def save_gateway(provider: Provider, data: GatewayInput, user=Depends(sas4.sas4_access), db=Depends(get_db)):
    merchant = data.merchant_id.strip()
    if not merchant:
        raise HTTPException(422, 'Merchant identifier is required')
    config = db.get(PaymentGateway, (user.id, provider))
    previous = decoded(config.encrypted_credentials) if config and not data.secret else {}
    if not data.secret and (not config or previous.get('merchant_id') != merchant or config.environment != data.environment):
        raise HTTPException(422, 'Enter the merchant secret when adding or changing the account or environment')
    secret = data.secret or previous.get('secret')
    if config is None:
        config = PaymentGateway(user_id=user.id, provider=provider)
        db.add(config)
    config.environment = data.environment
    config.encrypted_credentials = cipher().encrypt(json.dumps({'merchant_id': merchant, 'secret': secret}).encode()).decode()
    config.updated_at = now()
    audit(db, user, 'payment.gateway.configure', provider)
    db.commit()
    return gateway_status(config)


def provider_json(response):
    if not 200 <= response.status_code < 300:
        raise PaymentError(f'Payment provider returned HTTP {response.status_code}. Check merchant setup or try again later.')
    if len(response.content) > 2 * 1024 * 1024:
        raise PaymentError('Payment provider returned too much data.')
    try:
        data = response.json()
        if not isinstance(data, dict):
            raise ValueError()
        return data
    except ValueError as exc:
        raise PaymentError('Payment provider returned an invalid response.') from exc


def provider_session(transport=None):
    return httpx.Client(timeout=httpx.Timeout(20, connect=5), follow_redirects=False, trust_env=False, transport=transport)


def fib_headers(client, base, credentials):
    data = provider_json(client.post(base + '/auth/realms/fib-online-shop/protocol/openid-connect/token',
        data={'grant_type': 'client_credentials', 'client_id': credentials['merchant_id'], 'client_secret': credentials['secret']}))
    token = data.get('access_token')
    if not isinstance(token, str) or not token or len(token) > 16384:
        raise PaymentError('FIB authentication failed. Check merchant credentials.')
    return {'Authorization': 'Bearer ' + token}


def create_provider_payment(order, transport=None):
    credentials = decoded(order.encrypted_credentials)
    base = BASES[(order.provider, order.environment)]
    with provider_session(transport) as client:
        if order.provider == 'fib':
            result = provider_json(client.post(base + '/protected/v1/payments', headers=fib_headers(client, base, credentials),
                json={'monetaryValue': {'amount': order.amount, 'currency': 'IQD'}, 'description': 'AirLink recharge ' + order.id[:12]}))
            payment_id = result.get('paymentId')
            if not isinstance(payment_id, str) or not re.fullmatch(r'[a-zA-Z0-9-]{1,128}', payment_id):
                raise PaymentError('FIB did not return a payment identifier.')
            qr = result.get('qrCode')
            if not isinstance(qr, str) or not qr.startswith('data:image/png;base64,'):
                raise PaymentError('FIB did not return a QR image.')
            return payment_id, {'qr_data': qr, 'code': result.get('readableCode'), 'valid_until': result.get('validUntil')}
        result = provider_json(client.post(base + '/api/v1/public/vending/qr', json={
            'storeId': credentials['merchant_id'], 'storePassword': credentials['secret'], 'orderId': order.id,
            'billAmount': int(sas4.money(order.amount)), 'currency': 'IQD', 'expiresIn': 15}))
        data = result.get('data') or {}
        qr = data.get('qrUrl')
        if result.get('code') != 200 or not isinstance(qr, str) or urlparse(qr).scheme != 'https' or urlparse(qr).username:
            raise PaymentError('FastPay did not return a valid QR payment. Check merchant setup.')
        return order.id, {'qr_url': qr}


def verify_provider_payment(order, transport=None):
    credentials = decoded(order.encrypted_credentials)
    base = BASES[(order.provider, order.environment)]
    with provider_session(transport) as client:
        if order.provider == 'fib':
            data = provider_json(client.get(base + f'/protected/v1/payments/{order.provider_id}/status', headers=fib_headers(client, base, credentials)))
            if data.get('paymentId') != order.provider_id:
                raise PaymentError('FIB payment identifier does not match.')
            status = data.get('status')
            if status == 'UNPAID':
                return 'pending'
            if status == 'DECLINED':
                return 'declined'
            if status != 'PAID':
                return 'pending'
            amount = data.get('amount') or {}
            received, currency = amount.get('amount'), amount.get('currency')
        else:
            credentials_body = {'storeId': credentials['merchant_id'], 'storePassword': credentials['secret'], 'orderId': order.id}
            state_response = provider_json(client.post(base + '/api/v1/public/vending/status', json=credentials_body))
            state_data = state_response.get('data') or {}
            if state_response.get('code') != 200 or state_data.get('merchant_order_id', state_data.get('order_id')) != order.id:
                raise PaymentError('FastPay payment status is unavailable or does not match.')
            if state_data.get('payment_status') == 'DECLINED':
                return 'declined'
            if state_data.get('payment_status') != 'PAID':
                return 'pending'
            # A QR status/IPN is not proof of payment; use the provider's validation endpoint.
            result = provider_json(client.post(base + '/api/v1/public/vending/validate', json={
                'storeId': credentials['merchant_id'], 'storePassword': credentials['secret'], 'orderId': order.id}))
            data = result.get('data') or {}
            if result.get('code') != 200 or str(data.get('status', '')).lower() != 'success':
                return 'pending'
            if data.get('merchant_order_id') != order.id or not data.get('gw_transaction_id'):
                raise PaymentError('FastPay payment identifier does not match.')
            received, currency = data.get('received_amount'), data.get('currency')
        try:
            matched = currency == order.currency and sas4.money(received) == sas4.money(order.amount)
        except ValueError:
            matched = False
        if not matched:
            raise PaymentError('Payment amount or currency does not match. Recharge has not been applied.')
        return 'paid'


def public_order(order):
    return {'id': order.id, 'provider': order.provider, 'environment': order.environment,
            'amount': order.amount, 'currency': order.currency, 'status': order.status,
            'checkout': order.checkout, 'detail': order.detail, 'user_id': order.sas4_user_id}


@router.post('/users/{user_id}')
def begin_payment(user_id: int, data: PaymentInput, user=Depends(sas4.sas4_access), db=Depends(get_db)):
    if user_id < 1:
        raise HTTPException(422, 'Invalid SAS4 user ID')
    existing = db.get(RechargePayment, data.transaction_id)
    if existing:
        if existing.user_id != user.id or existing.sas4_user_id != user_id or existing.provider != data.provider:
            raise HTTPException(409, 'Payment request identifier is already in use.')
        return public_order(existing)
    outstanding = db.scalar(select(RechargePayment).where(RechargePayment.user_id == user.id,
        RechargePayment.sas4_user_id == user_id, RechargePayment.status.in_(['creating', 'pending', 'activating', 'paid_review', 'creation_unknown', 'review_required'])).limit(1))
    if outstanding:
        return public_order(outstanding)
    config = db.get(PaymentGateway, (user.id, data.provider))
    if not config:
        raise HTTPException(409, 'Configure this payment provider in My account first.')
    connection, password = sas4.local_user_connection(db, user)
    try:
        quote = sas4.fetch_recharge(connection, password, user_id)
        if not quote['methods']['credit']:
            raise HTTPException(403, 'SAS4 manager balance activation permission is required for paid recharges.')
        amount = sas4.money(quote['customer_price'])
        cost = sas4.money(quote['manager_cost'])
        if quote['currency'] != 'IQD' or amount <= 0:
            raise HTTPException(409, 'Bank payments require a positive SAS4 selling price in IQD.')
        if data.provider == 'fastpay' and (amount < 1000 or amount != amount.to_integral_value()):
            raise HTTPException(409, 'FastPay requires a whole IQD amount of at least 1,000.')
        if amount != sas4.money(data.expected_amount) or cost != sas4.money(data.expected_cost) or quote['profile_id'] != data.expected_profile_id or quote['expiration'] != data.expected_expiration:
            raise HTTPException(409, 'Service details or price changed. Reopen recharge to review the new amount.')
        balance = str(quote.get('manager_balance') or '').replace('IQD', '').replace(',', '').strip()
        if sas4.money(balance) < cost:
            raise HTTPException(409, 'SAS4 manager balance is insufficient. Top it up before accepting this payment.')
    except (ValueError, sas4.SAS4Error) as exc:
        raise HTTPException(409, 'SAS4 price or balance could not be verified. No payment was created.') from exc
    order = RechargePayment(id=data.transaction_id, user_id=user.id, sas4_user_id=user_id, sas4_username=connection.username,
        provider=data.provider, environment=config.environment, encrypted_credentials=config.encrypted_credentials,
        status='creating', amount=str(amount), currency='IQD', quote={k: quote[k] for k in ('profile_id', 'expiration', 'manager_cost')})
    # Serialize reservation of a payment slot for this subscriber across browser tabs.
    from .api import cache
    from redis.exceptions import RedisError, WatchError
    lock_key = f'payment:create:{user.id}:{user_id}'
    try:
        locked = cache.set(lock_key, order.id, nx=True, ex=60)
    except RedisError as exc:
        raise HTTPException(503, 'Payment protection is unavailable. Try again later.') from exc
    if not locked:
        raise HTTPException(409, 'A payment is already being prepared for this user.')
    try:
        outstanding = db.scalar(select(RechargePayment).where(RechargePayment.user_id == user.id,
            RechargePayment.sas4_user_id == user_id, RechargePayment.status.in_(['creating', 'pending', 'activating', 'paid_review', 'creation_unknown', 'review_required'])).limit(1))
        if outstanding:
            return public_order(outstanding)
        db.add(order)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(409, 'This payment request is already being created.')
    finally:
        try:
            with cache.pipeline() as pipe:
                pipe.watch(lock_key)
                if pipe.get(lock_key) == order.id:
                    pipe.multi()
                    pipe.delete(lock_key)
                    pipe.execute()
        except (RedisError, WatchError):
            pass  # The short-lived reservation expires without risking a repeated payment.

    try:
        order.provider_id, order.checkout = create_provider_payment(order)
        order.status = 'pending'
        audit(db, user, 'payment.create', order.id)
    except (PaymentError, httpx.HTTPError) as exc:
        order.status = 'creation_unknown'
        order.detail = 'Payment creation was not confirmed. Check the merchant portal before creating another payment.'
    order.updated_at = now()
    db.commit()
    return public_order(order)


def reconcile_order(db, order):
    if order.status != 'pending':
        return
    if aware(order.created_at) < now() - timedelta(hours=24):
        order.status, order.detail = 'review_required', 'Payment verification timed out. Check the merchant portal before retrying.'
        db.commit()
        return
    try:
        status = verify_provider_payment(order)
    except (PaymentError, httpx.HTTPError) as exc:
        order.detail = str(exc) if isinstance(exc, PaymentError) else 'Provider verification is temporarily unavailable; checking again automatically.'
        order.updated_at = now()
        db.commit()
        return
    if status == 'pending':
        if order.detail:
            order.detail = None
            db.commit()
        return
    # Compare-and-set means simultaneous polling workers cannot activate twice.
    new_status = 'sandbox_paid' if status == 'paid' and order.environment == 'sandbox' else 'activating' if status == 'paid' else 'declined'
    claimed = db.execute(update(RechargePayment).where(RechargePayment.id == order.id, RechargePayment.status == 'pending').values(status=new_status, updated_at=now())).rowcount
    db.commit()
    db.refresh(order)
    if not claimed or new_status != 'activating':
        return
    actor = db.get(User, order.user_id) if order.user_id else None
    connection = db.get(SAS4UserConnection, order.user_id) if order.user_id else None
    if not actor or not actor.active or actor.role not in ('owner', 'manager') or not connection or connection.username != order.sas4_username:
        order.status, order.detail = 'paid_review', 'Payment received. SAS4 account access changed; activation requires review.'
        db.commit()
        return
    try:
        password = cipher().decrypt(connection.encrypted_password.encode()).decode()
        request = sas4.CardRecharge(method='credit', transaction_id=order.id, expected_cost=order.quote['manager_cost'],
            expected_profile_id=order.quote['profile_id'], expected_expiration=order.quote['expiration'])
        sas4.redeem_card(connection, password, order.sas4_user_id, request)
        order.status, order.detail = 'completed', 'Payment verified and service recharged.'
        audit(db, actor, 'payment.recharge', order.id)
    except Exception:
        # Never repeat an activation after a timeout or uncertain result.
        order.status, order.detail = 'paid_review', 'Payment received, but recharge was not confirmed. Check SAS4 before applying service again.'
    order.updated_at = now()
    db.commit()


@router.get('/users/{user_id}')
def user_payments(user_id: int, user=Depends(sas4.sas4_access), db=Depends(get_db)):
    rows = db.scalars(select(RechargePayment).where(RechargePayment.user_id == user.id, RechargePayment.sas4_user_id == user_id)
        .order_by(RechargePayment.created_at.desc()).limit(10)).all()
    return [public_order(row) for row in rows]


@router.get('/orders/{order_id}')
def payment_status(order_id: str, user=Depends(sas4.sas4_access), db=Depends(get_db)):
    order = db.get(RechargePayment, order_id)
    if not order or order.user_id != user.id:
        raise HTTPException(404, 'Payment not found')
    return public_order(order)


def process_pending():
    with SessionLocal() as db:
        rows = db.scalars(select(RechargePayment).where(RechargePayment.status == 'pending').order_by(RechargePayment.created_at).limit(50)).all()
        for row in rows:
            try:
                reconcile_order(db, row)
            except Exception:
                db.rollback()
        stale = now() - timedelta(minutes=5)
        db.execute(update(RechargePayment).where(RechargePayment.status == 'creating', RechargePayment.updated_at < stale)
            .values(status='creation_unknown', detail='Payment creation was interrupted. Check the merchant portal before retrying.'))
        db.execute(update(RechargePayment).where(RechargePayment.status == 'activating', RechargePayment.updated_at < stale)
            .values(status='paid_review', detail='Payment received; activation was interrupted. Check SAS4 before retrying.'))
        db.commit()


async def payment_worker():
    while True:
        try:
            await asyncio.to_thread(process_pending)
        except Exception:
            pass  # Retry after transient database failures; no payment is replayed.
        await asyncio.sleep(20)
