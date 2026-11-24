"""Provider-verified IQD payments. Only explicit checkout requests create payments.
FIB: https://fib.iq/integrations/web-payments/
FastPay QR/validation: https://developer.fast-pay.iq/qr-integration
"""
import asyncio
import json
import re
from datetime import datetime, timedelta
from typing import Literal, Optional
from urllib.parse import urlparse
import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select, update, or_
from sqlalchemy.exc import IntegrityError
from . import sas4, section_access, radius_pin
from .db import get_db, SessionLocal
from .models import (PaymentGateway, SharedPaymentGateway, RechargePayment, RechargeCardReservation,
                     SavedRechargeCard, RadiusCardReservation, SAS4UserConnection, User, now, audit)
from .security import cipher, aware, owner

router = APIRouter(prefix='/api/payments', tags=['Payments'])
Provider = Literal['fib', 'fastpay']
Environment = Literal['sandbox', 'production']
FIB_PAYMENT_WINDOW = timedelta(minutes=5)
BASES = {
    # The legacy dotted staging host issues tokens rejected by the payment API.
    ('fib', 'sandbox'): 'https://fib-stage.fib.iq', ('fib', 'production'): 'https://fib.prod.fib.iq',
    ('fastpay', 'sandbox'): 'https://staging-qr.fast-pay.iq', ('fastpay', 'production'): 'https://qr.fast-pay.iq',
}


class PaymentError(Exception):
    pass


class PaymentNotCreated(PaymentError):
    """A failure before submission, or an explicit rejection of creation."""


class CreationReview(BaseModel):
    model_config = ConfigDict(extra='forbid')
    confirmed_not_created: Literal[True]


class GatewayInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    environment: Environment = 'sandbox'
    merchant_id: str = Field(min_length=1, max_length=255)
    secret: Optional[str] = Field(default=None, max_length=2048)


class PaymentInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    provider: Provider
    transaction_id: str = Field(pattern=r'^[a-f0-9]{32}$')
    expected_amount: Optional[str] = Field(default=None, max_length=40)
    expected_cost: Optional[str] = Field(default=None, max_length=40)
    expected_profile_id: int = Field(ge=1)
    expected_expiration: Optional[str] = Field(default=None, max_length=80)
    card_id: Optional[str] = Field(default=None, max_length=36)
    card_source: Literal['radius_pin', 'saved_pin'] = 'radius_pin'
    radius_card_id: Optional[int] = Field(default=None, ge=1)
    radius_series: Optional[str] = Field(default=None, min_length=1, max_length=128, pattern=r'^[A-Za-z0-9_-]+$')


def decoded(secret):
    try:
        return json.loads(cipher().decrypt(secret.encode()).decode())
    except Exception as exc:
        raise PaymentError('Merchant credentials cannot be read. Ask the owner to save Payment setup again.') from exc


def gateway_status(config):
    return {'provider': config.provider, 'environment': config.environment, 'configured': True,
            'merchant_id': decoded(config.encrypted_credentials)['merchant_id'], 'has_secret': True}


@router.get('/gateways')
def gateways(user=Depends(owner), db=Depends(get_db)):
    configs = shared_gateways(db)
    return [gateway_status(configs[p]) if p in configs else {'provider': p, 'configured': False, 'environment': 'sandbox', 'merchant_id': '', 'has_secret': False} for p in ('fib', 'fastpay')]


@router.get('/methods')
def payment_methods(user=Depends(sas4.sas4_access), db=Depends(get_db)):
    # Checkout only needs availability; merchant configuration stays owner-only.
    configs = shared_gateways(db)
    return [{'provider': p, 'configured': p in configs,
             'environment': configs[p].environment if p in configs else 'sandbox'} for p in ('fib', 'fastpay')]


def shared_gateway(db, provider):
    selected = db.get(SharedPaymentGateway, provider)
    actor = db.get(User, selected.user_id) if selected and selected.user_id else None
    if not actor or not actor.active or not section_access.has_capability(actor, 'payment_gateways', db, write=True):
        return None
    return db.get(PaymentGateway, (actor.id, provider))


def shared_gateways(db):
    return {provider: config for provider in ('fib', 'fastpay')
            if (config := shared_gateway(db, provider)) is not None}


@router.put('/gateways/{provider}')
def save_gateway(provider: Provider, data: GatewayInput, user=Depends(owner), db=Depends(get_db)):
    merchant = data.merchant_id.strip()
    if not merchant:
        raise HTTPException(422, 'Merchant identifier is required')
    config = db.get(PaymentGateway, (user.id, provider))
    current = shared_gateway(db, provider)
    previous = decoded(current.encrypted_credentials) if current and not data.secret else {}
    if not data.secret and (not current or previous.get('merchant_id') != merchant or current.environment != data.environment):
        raise HTTPException(422, 'Enter the merchant secret when adding or changing the account or environment')
    secret = data.secret or previous.get('secret')
    if config is None:
        config = PaymentGateway(user_id=user.id, provider=provider)
        db.add(config)
    config.environment = data.environment
    config.encrypted_credentials = cipher().encrypt(json.dumps({'merchant_id': merchant, 'secret': secret}).encode()).decode()
    config.updated_at = now()
    selected = db.get(SharedPaymentGateway, provider)
    if selected is None:
        selected = SharedPaymentGateway(provider=provider)
        db.add(selected)
    selected.user_id = user.id
    audit(db, user, 'payment.gateway.configure', provider)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, 'Payment setup changed while saving. Reload the settings and try again.') from None
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
    # Authentication cannot create a payment. Never treat its failure as an
    # uncertain charge, and never include provider bodies or secrets in errors.
    try:
        response = client.post(base + '/auth/realms/fib-online-shop/protocol/openid-connect/token',
            data={'grant_type': 'client_credentials', 'client_id': credentials['merchant_id'], 'client_secret': credentials['secret']})
    except httpx.HTTPError as exc:
        raise PaymentError('FIB authentication could not be reached. Check your internet connection and try again.') from exc
    if response.status_code in (400, 401, 403):
        raise PaymentError('FIB rejected the merchant credentials. The owner must check the FIB client ID, client secret, and Sandbox/Production environment in My account → Payment setup.')
    try:
        data = provider_json(response)
    except PaymentError as exc:
        raise PaymentError(f'FIB authentication failed (HTTP {response.status_code}). Check Payment setup or try again later.') from exc
    token = data.get('access_token')
    if not isinstance(token, str) or not token or len(token) > 16384:
        raise PaymentError('FIB did not return an authentication token. Check merchant credentials.')
    return {'Authorization': 'Bearer ' + token}


@router.post('/gateways/fib/test')
def test_fib_connection(user=Depends(owner), db=Depends(get_db)):
    section_access.require_any(user, ('payment_gateways',), db, write=True)
    config = shared_gateway(db, 'fib')
    if not config:
        raise HTTPException(409, 'Save the FIB merchant settings first.')
    try:
        credentials = decoded(config.encrypted_credentials)
        with provider_session() as client:
            base = BASES[('fib', config.environment)]
            headers = fib_headers(client, base, credentials)
            # A token alone is insufficient: check the protected API using a
            # nonexistent UUID. This never creates or changes a payment.
            response = client.get(base + '/protected/v1/payments/00000000-0000-0000-0000-000000000000/status', headers=headers)
    except PaymentError as exc:
        return {'authenticated': False, 'payment_api_access': False, 'environment': config.environment, 'detail': str(exc)}
    except httpx.HTTPError:
        return {'authenticated': True, 'payment_api_access': False, 'environment': config.environment,
                'detail': 'FIB authentication succeeded, but the payment API could not be reached. No payment was created.'}
    if response.status_code not in (200, 404):
        return {'authenticated': True, 'payment_api_access': False, 'environment': config.environment,
                'detail': f'FIB issued a token, but the payment API check failed (HTTP {response.status_code}). Check the API environment and merchant permissions. No payment was created.'}
    return {'authenticated': True, 'payment_api_access': True, 'environment': config.environment,
            'detail': 'FIB authentication and payment API access succeeded. No payment was created.'}


def fib_app_links(result, environment):
    links = {}
    for kind in ('personal', 'business', 'corporate'):
        value = result.get(kind + 'AppLink')
        if not isinstance(value, str) or len(value) > 8192:
            continue
        try:
            url = urlparse(value)
            hosts = ({f'{kind}.stage.first-iraqi-bank.co', f'{kind[0]}-stage.fib.iq'} if environment == 'sandbox'
                     else {f'{kind}.first-iraqi-bank.co', f'{kind}.prod.first-iraqi-bank.co', f'{kind[0]}.fib.iq'})
            if url.scheme == 'https' and url.hostname in hosts and not url.username and not url.password and url.port in (None, 443):
                links[kind] = value
        except ValueError:
            continue
    return links


def create_provider_payment(order, transport=None):
    try:
        credentials = decoded(order.encrypted_credentials)
    except PaymentError as exc:
        raise PaymentNotCreated(str(exc) + ' No payment was created.') from exc
    base = BASES[(order.provider, order.environment)]
    with provider_session(transport) as client:
        if order.provider == 'fib':
            try:
                headers = fib_headers(client, base, credentials)
            except PaymentError as exc:
                raise PaymentNotCreated(str(exc) + ' No payment was created.') from exc
            try:
                response = client.post(base + '/protected/v1/payments', headers=headers,
                    json={'monetaryValue': {'amount': order.amount, 'currency': 'IQD'},
                          'description': 'AirLink recharge ' + order.id[:12], 'expiresIn': 'PT5M'})
            except (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout) as exc:
                raise PaymentNotCreated('Could not connect to FIB to create the payment. No payment was submitted. Try again.') from exc
            if response.status_code == 401:
                raise PaymentNotCreated('FIB rejected the payment API token (HTTP 401). No payment was created. Check the API environment and FIB token authorization.')
            if response.status_code in (400, 403, 404, 405, 415, 422, 429):
                raise PaymentNotCreated(f'FIB rejected payment creation (HTTP {response.status_code}). No payment was created. Check merchant permissions, payment details, or try again later.')
            result = provider_json(response)
            payment_id = result.get('paymentId')
            if not isinstance(payment_id, str) or not re.fullmatch(r'[a-zA-Z0-9-]{1,128}', payment_id):
                raise PaymentError('FIB did not return a payment identifier.')
            qr = result.get('qrCode')
            if not isinstance(qr, str) or not qr.startswith('data:image/png;base64,'):
                raise PaymentError('FIB did not return a QR image.')
            checkout = {'qr_data': qr, 'code': result.get('readableCode'), 'valid_until': result.get('validUntil')}
            links = fib_app_links(result, order.environment)
            if links:
                checkout['app_links'] = links
            return payment_id, checkout
        result = provider_json(client.post(base + '/api/v1/public/vending/qr', json={
            'storeId': credentials['merchant_id'], 'storePassword': credentials['secret'], 'orderId': order.id,
            'billAmount': int(sas4.money(order.amount)), 'currency': 'IQD', 'expiresIn': 15}))
        data = result.get('data') or {}
        qr = data.get('qrUrl')
        if result.get('code') != 200 or not isinstance(qr, str) or urlparse(qr).scheme != 'https' or urlparse(qr).username:
            raise PaymentError('FastPay did not return a valid QR payment. Check merchant setup.')
        return order.id, {'qr_url': qr}


def payment_time(value):
    if not isinstance(value, str):
        return None
    try:
        return aware(datetime.fromisoformat(value.replace('Z', '+00:00')))
    except ValueError:
        return None


def fib_deadline(order):
    if order.provider != 'fib':
        return None
    created = getattr(order, 'created_at', None)
    local = aware(created) + FIB_PAYMENT_WINDOW if created else None
    bank = payment_time((getattr(order, 'checkout', None) or {}).get('valid_until'))
    deadlines = [value for value in (local, bank) if value is not None]
    return min(deadlines) if deadlines else None


def cancel_fib_payment(order, transport=None):
    credentials = decoded(order.encrypted_credentials)
    base = BASES[('fib', order.environment)]
    with provider_session(transport) as client:
        response = client.post(base + f'/protected/v1/payments/{order.provider_id}/cancel',
                               headers=fib_headers(client, base, credentials))
        if response.status_code != 204:
            raise PaymentError(f'FIB cancellation was not confirmed (HTTP {response.status_code}).')


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
                return 'expired' if data.get('decliningReason') == 'PAYMENT_EXPIRATION' else 'declined'
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
        deadline = fib_deadline(order)
        if deadline:
            paid_at = payment_time(data.get('paidAt'))
            if (paid_at and paid_at > deadline) or (now() >= deadline and paid_at is None):
                return 'paid_review'
        return 'paid'


def public_order(order):
    deadline = fib_deadline(order)
    return {'id': order.id, 'provider': order.provider, 'environment': order.environment,
            'amount': order.amount, 'currency': order.currency, 'status': order.status,
            'checkout': order.checkout, 'detail': order.detail, 'user_id': order.sas4_user_id,
            'fulfillment': order.quote.get('fulfillment', 'credit'),
            'auto_recharge': order.quote.get('auto_recharge') is True,
            'card_label': order.quote.get('card_label'), 'profile': order.quote.get('profile'),
            'profile_id': order.quote.get('profile_id'),
            'expires_at': deadline.isoformat() if deadline else None,
            'can_review_creation': order.provider == 'fib' and order.status == 'creation_unknown' and not order.provider_id}


@router.get('/users/{user_id}/radius-card')
def radius_card_quote(user_id: int, user=Depends(sas4.sas4_access), db=Depends(get_db)):
    section_access.require_any(user, ('fib_recharge',), db)
    if user_id < 1:
        raise HTTPException(422, 'Invalid SAS4 user ID')
    connection, password = sas4.local_user_connection(db, user)
    try:
        quote = sas4.fetch_recharge(connection, password, user_id)
        if not quote['methods'].get('card'):
            raise HTTPException(403, 'SAS4 card recharge permission is required.')
        card = radius_pin.find_card(connection, password, quote['profile_id'], db)
        # PINs never leave the backend, even in checkout previews.
        return {'items': [{k: v for k, v in card.items() if k != 'pin'}] if card else []}
    except (sas4.SAS4Error, ValueError) as exc:
        raise HTTPException(409, str(exc)) from exc


def release_card(db, order):
    for model in (RechargeCardReservation, RadiusCardReservation):
        reservation = db.scalar(select(model).where(model.payment_id == order.id))
        if reservation:
            db.delete(reservation)


@router.post('/users/{user_id}')
def begin_payment(user_id: int, data: PaymentInput, user=Depends(sas4.sas4_access), db=Depends(get_db)):
    return begin_customer_payment(user_id, data, user, db)


def begin_customer_payment(user_id, data, user, db, package_profile_id=None):
    if data.provider == 'fib':
        section_access.require_any(user, ('fib_recharge',), db, write=True)
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
    config = shared_gateway(db, data.provider)
    if not config:
        raise HTTPException(409, 'This payment method is not configured. Ask the owner to complete Payment setup.')
    radius = data.provider == 'fib' and data.card_source == 'radius_pin'
    if data.provider == 'fib':
        if not radius and not section_access.has_capability(user, 'card_system', db, write=True):
            raise HTTPException(403, 'Owner access is required to issue cards from Card System.')
        amount = None  # Loaded from the reserved card, never from a customer-entered amount.
    connection, password = sas4.local_user_connection(db, user)
    try:
        quote = sas4.fetch_recharge(connection, password, user_id)
        if data.provider == 'fib' and not quote['methods'].get('card'):
            raise HTTPException(403, 'SAS4 card recharge permission is required.')
        if data.provider != 'fib' and not quote['methods']['credit']:
            raise HTTPException(403, 'SAS4 manager balance activation permission is required for paid recharges.')
        if data.provider != 'fib':
            amount = sas4.money(quote['customer_price'])
            cost = sas4.money(quote['manager_cost'])
            if quote['currency'] != 'IQD' or amount <= 0:
                raise HTTPException(409, 'Bank payments require a positive SAS4 selling price in IQD.')
            if amount < 1000 or amount != amount.to_integral_value():
                raise HTTPException(409, 'FastPay requires a whole IQD amount of at least 1,000.')
            if amount != sas4.money(data.expected_amount) or cost != sas4.money(data.expected_cost):
                raise HTTPException(409, 'Service details or price changed. Reopen recharge to review the new amount.')
            balance = str(quote.get('manager_balance') or '').replace('IQD', '').replace(',', '').strip()
            if sas4.money(balance) < cost:
                raise HTTPException(409, 'SAS4 manager balance is insufficient. Top it up before accepting this payment.')
        if quote['profile_id'] != data.expected_profile_id or quote['expiration'] != data.expected_expiration:
            raise HTTPException(409, 'Service details or price changed. Reopen recharge to review the new amount.')
    except (ValueError, sas4.SAS4Error) as exc:
        raise HTTPException(409, 'SAS4 price or balance could not be verified. No payment was created.') from exc
    package = None
    if package_profile_id is not None:
        if not radius:
            raise HTTPException(422, 'Package selection requires FIB SAS4 card checkout.')
        from .client_packages import validate_package
        try:
            package = validate_package(connection, password, user_id, package_profile_id, quote['profile_id'], quote['expiration'])
        except (sas4.SAS4Error, httpx.HTTPError):
            raise HTTPException(409, 'SAS4 package details could not be verified. No payment was created.') from None
    order = RechargePayment(id=data.transaction_id, user_id=user.id, sas4_user_id=user_id, sas4_username=connection.username,
        provider=data.provider, environment=config.environment, encrypted_credentials=config.encrypted_credentials,
        status='creating', amount=str(amount), currency='IQD', quote={
            **{k: quote[k] for k in ('profile_id', 'expiration', 'manager_cost')}, 'merchant_owner_id': config.user_id})
    # Serialize reservation of a payment slot for this subscriber across browser tabs.
    from .api import cache
    from redis.exceptions import RedisError, WatchError
    lock_key = f'payment:create:{user.id}:{user_id}'
    try:
        locked = cache.set(lock_key, order.id, nx=True, ex=300 if radius else 60)
    except RedisError as exc:
        raise HTTPException(503, 'Payment protection is unavailable. Try again later.') from exc
    if not locked:
        raise HTTPException(409, 'A payment is already being prepared for this user.')
    try:
        outstanding = db.scalar(select(RechargePayment).where(RechargePayment.user_id == user.id,
            RechargePayment.sas4_user_id == user_id, RechargePayment.status.in_(['creating', 'pending', 'activating', 'paid_review', 'creation_unknown', 'review_required'])).limit(1))
        if outstanding:
            return public_order(outstanding)
        if radius:
            if data.radius_card_id is None or data.radius_series is None:
                raise HTTPException(409, 'Refresh the SAS4 card quote before paying.')
            try:
                candidate = radius_pin.find_card(connection, password, package_profile_id if package else quote['profile_id'], db,
                    card_id=data.radius_card_id, series=data.radius_series)
                if not candidate:
                    raise HTTPException(409, 'This SAS4 PIN is no longer available. Refresh before paying.')
                amount = sas4.money(candidate['price_iqd'])
                if amount != sas4.money(data.expected_amount):
                    raise HTTPException(409, 'The SAS4 card value changed. Refresh and review the amount.')
            except (sas4.SAS4Error, ValueError) as exc:
                raise HTTPException(409, 'SAS4 card availability or value could not be verified. No payment was created.') from exc
            order.amount = str(amount)
            order.quote = {**order.quote, 'fulfillment': 'radius_pin', 'auto_recharge': True,
                'card_label': candidate['label'], 'profile': quote.get('profile'),
                'radius_series': candidate['series'], 'radius_card_id': int(candidate['id'])}
            if package:
                order.quote = {**order.quote, 'profile': package['name'], 'profile_id': package['profile_id']}
                if package['profile_id'] != quote['profile_id']:
                    order.quote = {**order.quote, 'previous_profile_id': quote['profile_id']}

        elif data.provider == 'fib':
            cards = select(SavedRechargeCard).where(
                SavedRechargeCard.user_id == user.id, SavedRechargeCard.profile_id == quote['profile_id'],
                SavedRechargeCard.price_iqd.is_not(None),
                ~select(RechargeCardReservation.card_id).where(RechargeCardReservation.card_id == SavedRechargeCard.id).exists())
            if data.card_id:
                cards = cards.where(SavedRechargeCard.id == data.card_id)
            card = db.scalar(cards.order_by(SavedRechargeCard.created_at.desc(), SavedRechargeCard.id).limit(1).with_for_update())
            if not card or db.get(RechargeCardReservation, card.id):
                raise HTTPException(409, 'No available card matches this customer profile. Assign a matching card in Card System and refresh.')
            try:
                amount = sas4.money(card.price_iqd)
                if amount <= 0 or amount != sas4.money(data.expected_amount):
                    raise ValueError()
            except ValueError:
                raise HTTPException(409, 'The card price changed or is unavailable. Refresh and review the price before paying.') from None
            order.amount = str(amount)
            try:
                pin = cipher().decrypt(card.encrypted_pin.encode()).decode()
                if not pin.strip():
                    raise ValueError('Empty PIN')
            except Exception:
                raise HTTPException(409, 'This saved PIN cannot be read. Replace it before paying.') from None
            order.quote = {**order.quote, 'fulfillment': 'saved_pin', 'auto_recharge': True,
                           'card_label': card.label, 'profile': quote.get('profile')}
        db.add(order)
        try:
            db.flush()
            if radius:
                db.add(RadiusCardReservation(source_key=radius_pin.source_key(int(candidate['id'])),
                    payment_id=order.id, series=candidate['series'], remote_card_id=int(candidate['id']),
                    encrypted_pin=cipher().encrypt(candidate['pin'].encode()).decode()))
            elif data.provider == 'fib':
                db.add(RechargeCardReservation(card_id=card.id, payment_id=order.id))
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(409, 'This payment or card is already reserved. Refresh before paying.')
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
    except PaymentNotCreated as exc:
        order.status, order.detail = 'creation_failed', str(exc)
        release_card(db, order)
        audit(db, user, 'payment.creation_failed', order.id)
    except (PaymentError, httpx.HTTPError) as exc:
        order.status = 'creation_unknown'
        reason = str(exc) if isinstance(exc, PaymentError) else 'The connection was interrupted after payment submission may have started.'
        order.detail = reason + ' Check FIB before retrying; the payment may already exist.'
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
        deadline = fib_deadline(order)
        if status == 'pending' and deadline and now() >= deadline:
            # Cancellation can race with payment. Always recheck the bank before
            # releasing inventory, even after a timeout or a successful 204.
            try:
                cancel_fib_payment(order)
            except (PaymentError, httpx.HTTPError):
                pass
            status = verify_provider_payment(order)
            if status == 'pending':
                order.detail = 'The five-minute payment window has expired. Confirming cancellation with FIB; the recharge PIN remains locked.'
                order.updated_at = now()
                db.commit()
                return
        if status == 'declined' and deadline and now() >= deadline:
            status = 'expired'
    except (PaymentError, httpx.HTTPError) as exc:
        order.detail = str(exc) if isinstance(exc, PaymentError) else 'Provider verification is temporarily unavailable; checking again automatically.'
        order.updated_at = now()
        db.commit()
        return
    if status == 'pending':
        order.detail = None
        order.updated_at = now()
        db.commit()
        return
    # Compare-and-set means simultaneous polling workers cannot activate twice.
    radius = order.quote.get('fulfillment') == 'radius_pin'
    pin_order = order.quote.get('fulfillment') in ('saved_pin', 'radius_pin')
    auto_card = pin_order and order.quote.get('auto_recharge') is True
    new_status = ('sandbox_paid' if status == 'paid' and order.environment == 'sandbox'
                  else 'pin_ready' if status == 'paid' and pin_order and not auto_card
                  else 'activating' if status == 'paid'
                  else 'paid_review' if status == 'paid_review'
                  else 'expired' if status == 'expired' else 'declined')
    claimed = db.execute(update(RechargePayment).where(RechargePayment.id == order.id, RechargePayment.status == 'pending').values(status=new_status, updated_at=now())).rowcount
    if claimed and pin_order:
        reservation = db.scalar(select(RechargeCardReservation).where(RechargeCardReservation.payment_id == order.id))
        if new_status in ('sandbox_paid', 'declined', 'expired'):
            release_card(db, order)
        elif new_status == 'pin_ready':
            if not reservation:
                order.status, order.detail = 'paid_review', 'Payment received, but the reserved card is missing. Contact the owner.'
            else:
                order.detail = 'Payment verified. Your recharge PIN is ready.'
                audit(db, db.get(User, order.user_id), 'payment.pin_issued', order.id)
    if claimed and new_status == 'expired':
        order.detail = 'Payment expired without payment. No recharge PIN was issued or used.'
        audit(db, db.get(User, order.user_id), 'payment.expired', order.id)
    elif claimed and new_status == 'paid_review':
        order.detail = 'Payment received, but payment within the five-minute window could not be verified. The PIN remains locked for owner review.'
    db.commit()
    db.refresh(order)
    if not claimed or new_status != 'activating':
        return
    actor = db.get(User, order.user_id) if order.user_id else None
    connection = db.get(SAS4UserConnection, order.user_id) if order.user_id else None
    if not actor or not actor.active or (auto_card and not radius and not section_access.has_capability(actor, 'card_system', db, write=True)) or (actor.role not in ('owner', 'manager') and section_access.role_policy(actor, db) is None) or not connection or connection.username != order.sas4_username:
        order.status, order.detail = 'paid_review', 'Payment received. SAS4 account access changed; activation requires review.'
        db.commit()
        return
    if (actor.role == 'manager' or section_access.role_policy(actor, db) is not None) and 'isp_card' not in section_access.editable(actor, db):
        order.status, order.detail = 'paid_review', 'Payment received. Recharge permission changed; activation requires review.'
        db.commit()
        return
    if actor.role != 'owner' and order.provider == 'fib' and 'fib_recharge' not in section_access.editable(actor, db):
        order.status, order.detail = 'paid_review', 'Payment received. FIB recharge permission changed; activation requires review.'
        db.commit()
        return
    try:
        password = cipher().decrypt(connection.encrypted_password.encode()).decode()
        if radius:
            reservation = db.scalar(select(RadiusCardReservation).where(RadiusCardReservation.payment_id == order.id))
            if not reservation:
                raise PaymentError('The reserved SAS4 PIN is missing. Owner review is required.')
            candidate = radius_pin.find_card(connection, password, order.quote['profile_id'], db,
                card_id=reservation.remote_card_id, series=reservation.series, payment_id=order.id)
            if (not candidate or sas4.money(candidate['price_iqd']) != sas4.money(order.amount)
                    or candidate['pin'] != cipher().decrypt(reservation.encrypted_pin.encode()).decode()):
                raise PaymentError('The reserved SAS4 PIN changed or was used outside AirLink. Owner review is required.')
            from .client_packages import apply_paid_package
            apply_paid_package(connection, password, order, db)
            request = sas4.CardRecharge(method='card', pin=candidate['pin'], transaction_id=order.id,
                expected_profile_id=order.quote['profile_id'], expected_expiration=order.quote['expiration'])
        elif auto_card:
            reservation = db.scalar(select(RechargeCardReservation).where(RechargeCardReservation.payment_id == order.id))
            card = db.get(SavedRechargeCard, reservation.card_id) if reservation else None
            if not card or card.user_id != actor.id or card.profile_id != order.quote['profile_id']:
                raise PaymentError('Reserved card is unavailable or does not match the paid profile.')
            request = sas4.CardRecharge(method='card', pin=cipher().decrypt(card.encrypted_pin.encode()).decode(),
                transaction_id=order.id, expected_profile_id=order.quote['profile_id'], expected_expiration=order.quote['expiration'])
        else:
            request = sas4.CardRecharge(method='credit', transaction_id=order.id, expected_cost=order.quote['manager_cost'],
                expected_profile_id=order.quote['profile_id'], expected_expiration=order.quote['expiration'])
        activation_result = sas4.redeem_card(connection, password, order.sas4_user_id, request)
        if activation_result.get('recharged') is not True:
            raise PaymentError('SAS4 did not confirm recharge.')
        order.status, order.detail = 'completed', 'Payment verified and service recharged.'
        audit(db, actor, 'payment.recharge', order.id)
    except Exception:
        # Never repeat an activation after a timeout or uncertain result.
        order.status, order.detail = 'paid_review', 'Payment received, but recharge was not confirmed. Check SAS4 before applying service again.'
    order.updated_at = now()
    db.commit()
    if order.status == 'completed':
        # Receipt problems must never turn a successful recharge into an
        # uncertain activation or cause the PIN to be submitted again.
        try:
            from . import customer_telegram
            receipt = dict(activation_result.get('_notification_receipt') or {})
            receipt.update(amount=str(order.amount), currency=order.currency, reference=order.id)
            if not auto_card:
                receipt['recharge_cost'] = str(sas4.money(order.quote['manager_cost']))
            receipt.pop('service_price', None)
            customer_telegram.activation(db, actor, order.sas4_user_id, order.provider, order.id, receipt)
            db.commit()
        except Exception:
            db.rollback()


@router.get('/users/{user_id}')
def user_payments(user_id: int, user=Depends(sas4.sas4_access), db=Depends(get_db)):
    scope = RechargePayment.user_id == user.id
    if section_access.has_capability(user, 'payment_gateways', db):
        scope = or_(scope, RechargePayment.quote['merchant_owner_id'].as_string() == user.id)
    rows = db.scalars(select(RechargePayment).where(scope, RechargePayment.sas4_user_id == user_id)
        .order_by(RechargePayment.created_at.desc()).limit(10)).all()
    return [public_order(row) for row in rows]


def may_view_order(user, order):
    return order and (order.user_id == user.id or
                      (section_access.has_capability(user, 'payment_gateways') and order.quote.get('merchant_owner_id') == user.id))


@router.get('/orders/{order_id}')
def payment_status(order_id: str, user=Depends(sas4.sas4_access), db=Depends(get_db)):
    order = db.get(RechargePayment, order_id)
    if not may_view_order(user, order):
        raise HTTPException(404, 'Payment not found')
    return public_order(order)


@router.post('/orders/{order_id}/review-creation')
def review_creation(order_id: str, data: CreationReview, user=Depends(sas4.sas4_access), db=Depends(get_db)):
    order = db.scalar(select(RechargePayment).where(RechargePayment.id == order_id).with_for_update())
    if not may_view_order(user, order):
        raise HTTPException(404, 'Payment not found')
    section_access.require_any(user, ('payment_gateways',), db, write=True)
    if order.provider != 'fib' or order.status != 'creation_unknown' or order.provider_id:
        raise HTTPException(409, 'Only unconfirmed FIB creation without a bank payment ID can be reviewed here.')
    claimed = db.execute(update(RechargePayment).where(
        RechargePayment.id == order.id, RechargePayment.status == 'creation_unknown',
        RechargePayment.provider_id.is_(None)).values(status='creation_failed', updated_at=now(),
        detail='The owner checked FIB and confirmed no payment was created or paid. The reserved card has been released.')).rowcount
    if not claimed:
        raise HTTPException(409, 'Payment status changed. Refresh before reviewing it.')
    release_card(db, order)
    audit(db, user, 'payment.creation_review_not_created', order.id)
    db.commit()
    db.refresh(order)
    return public_order(order)


@router.post('/orders/{order_id}/pin')
def payment_pin(order_id: str, user=Depends(sas4.sas4_access), db=Depends(get_db)):
    order = db.get(RechargePayment, order_id)
    if not order or order.user_id != user.id:
        raise HTTPException(404, 'Payment not found')
    if (order.status != 'pin_ready' or order.environment != 'production'
            or order.quote.get('fulfillment') != 'saved_pin' or order.quote.get('auto_recharge') is True):
        raise HTTPException(409, 'A recharge PIN is available only after verified production payment.')
    reservation = db.scalar(select(RechargeCardReservation).where(RechargeCardReservation.payment_id == order.id))
    card = db.get(SavedRechargeCard, reservation.card_id) if reservation else None
    if not card or card.user_id != user.id:
        raise HTTPException(409, 'The issued card is unavailable. Contact the owner.')
    try:
        pin = cipher().decrypt(card.encrypted_pin.encode()).decode()
    except Exception:
        raise HTTPException(409, 'The issued PIN cannot be read. Contact the owner.') from None
    audit(db, user, 'payment.read_pin', order.id)
    db.commit()
    return {'pin': pin}


def process_pending(saved_pin_only=False):
    with SessionLocal() as db:
        scope = RechargePayment.quote['fulfillment'].as_string().in_(['saved_pin', 'radius_pin']) if saved_pin_only else True
        rows = db.scalars(select(RechargePayment).where(RechargePayment.status == 'pending', scope)
            .order_by(RechargePayment.updated_at, RechargePayment.created_at).limit(50)).all()
        for row in rows:
            try:
                reconcile_order(db, row)
            except Exception:
                db.rollback()
        stale = now() - timedelta(minutes=5)
        db.execute(update(RechargePayment).where(RechargePayment.status == 'creating', RechargePayment.updated_at < stale, scope)
            .values(status='creation_unknown', detail='Payment creation was interrupted. Check the merchant portal before retrying.'))
        db.execute(update(RechargePayment).where(RechargePayment.status == 'activating', RechargePayment.updated_at < stale, scope)
            .values(status='paid_review', detail='Payment received; activation was interrupted. Check SAS4 before retrying.'))
        db.commit()


async def payment_worker(saved_pin_only=False):
    while True:
        try:
            await asyncio.to_thread(process_pending, saved_pin_only)
        except Exception:
            pass  # Retry after transient database failures; no payment is replayed.
        await asyncio.sleep(20)
