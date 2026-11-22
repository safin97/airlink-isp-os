import json
from datetime import timedelta
from types import SimpleNamespace as NS
import pytest
from sqlalchemy import select
from telethon import errors
from airlink import recharge_telegram as rt, customer_telegram as ct, sas4, payments, api
from airlink.db import SessionLocal
from airlink.models import User, SAS4UserConnection, RechargePayment, now
from test_telegram_account import telegram, connect, clear_rate, PERSON
from test_api import user
from test_sas4 import SETTINGS
from test_payments import setup_checkout

PATH = '/api/integrations/recharge-telegram'


@pytest.fixture
def receipts(client, owner, telegram, monkeypatch):
    connect(client, owner)
    assert client.put('/api/integrations/sas4', headers=owner, json=SETTINGS).status_code == 200
    record = {'username': 'customer', 'phone': '+9647501234567', 'profile_name': '20 Mbps',
              'expiration': '2027-01-01 18:00:00', 'password': 'PRIVATE_PASSWORD'}
    monkeypatch.setattr(ct, 'record_for', lambda db, actor, cid: dict(record))
    assert client.put(PATH, headers=owner, json={'enabled': True}).status_code == 200
    return telegram, record


def receipt(record):
    return {'username': record['username'], 'phone_hash': ct.phone_hash(record),
            'profile': record['profile_name'], 'expiration': record['expiration'],
            'card': '••••1234', 'reference': 'a' * 32}


def enqueue(receipts, kind='card', actor_id=None):
    telegram, record = receipts
    with SessionLocal() as db:
        actor = db.get(User, actor_id or telegram[0])
        ct.activation(db, actor, 7, kind, 'a' * 32, receipt(record))
        db.commit()
        return db.scalar(select(rt.Event)).id


def deliver(event_id):
    with SessionLocal() as db:
        event = db.get(rt.Event, event_id)
        rt.deliver(db, event)
        return event.status, event.detail


@pytest.mark.parametrize('method', ['card', 'credit', 'extend', 'fib', 'fastpay'])
def test_all_recharge_types_send_receipt_once_from_selected_owner(client, owner, receipts, method):
    event_id = enqueue(receipts, method)
    assert enqueue(receipts, method) == event_id
    assert deliver(event_id)[0] == 'sent'
    assert deliver(event_id)[0] == 'sent'
    sent = [c[1] for c in receipts[0][1] if isinstance(c, tuple) and c[0] == 'send']
    assert len(sent) == 1
    assert '20 Mbps' in sent[0].message and '2027-01-01' in sent[0].message
    assert '••••1234' in sent[0].message and 'a' * 32 in sent[0].message
    assert 'PRIVATE' not in sent[0].message and '+964' not in sent[0].message
    assert sent[0].peer.user_id == PERSON.id and sent[0].allow_paid_stars is None
    with SessionLocal() as db:
        assert db.scalar(select(ct.Event)) is None
        assert 'customer' not in db.get(rt.Event, event_id).encrypted_payload
    result = client.get('/api/integrations/customer-telegram/users/7', headers=owner)
    assert result.json()['account_recharges'][0]['status'] == 'sent'


@pytest.mark.parametrize('method', ['card', 'credit', 'extend', 'fib', 'fastpay'])
def test_real_recharge_hooks_for_manager_only_queue_confirmed_success(client, owner, receipts, monkeypatch, method):
    mid, manager = user(client, owner, 'manager', name='recharge-manager')
    client.put('/api/integrations/sas4', headers=manager, json=SETTINGS)
    activations = []
    def activate(*args, **kwargs):
        activations.append(1)
        return {'recharged': True, '_notification_receipt': receipt(receipts[1])}
    monkeypatch.setattr(sas4, 'redeem_card', activate)
    if method in ('fib', 'fastpay'):
        with SessionLocal() as db:
            db.add(RechargePayment(id='b' * 32, user_id=mid, sas4_user_id=7, sas4_username=SETTINGS['username'],
                provider=method, environment='production', amount='2500', currency='IQD', status='pending',
                encrypted_credentials=ct.cipher().encrypt(b'{}').decode(), provider_id='fixture',
                quote={'manager_cost': '2000', 'profile_id': 3, 'expiration': '2026-11-01'}))
            db.commit()
        monkeypatch.setattr(payments, 'verify_provider_payment', lambda order: 'paid')
        payments.process_pending()
        payments.process_pending()
    else:
        body = {'method': method, 'pin': 'PRIVATE_PIN', 'transaction_id': 'b' * 32,
                'expected_cost': '0', 'expected_profile_id': 3, 'extension_id': 1}
        for _ in range(2):
            result = client.post('/api/integrations/sas4/users/7/recharge', headers=manager, json=body)
            assert result.status_code == 200 and '_notification_receipt' not in result.text
    assert len(activations) == 1
    with SessionLocal() as db:
        events = db.scalars(select(rt.Event)).all()
        assert len(events) == 1 and events[0].user_id == receipts[0][0] and events[0].actor_id == mid
        rt.deliver(db, events[0])
        assert events[0].status == 'sent'
        if method in ('fib', 'fastpay'):
            assert rt.payload(events[0])['receipt']['amount'] == '2500'
            assert rt.payload(events[0])['receipt']['recharge_cost'] == '2000'
            sent = [c[1].message for c in receipts[0][1] if isinstance(c, tuple) and c[0] == 'send']
            assert 'Recharge cost: 2000 IQD' in sent[-1] and '2500' not in sent[-1]


@pytest.mark.parametrize('outcome', ['pending', 'declined', 'sandbox', 'unconfirmed'])
def test_unpaid_sandbox_and_unconfirmed_activation_never_queue(client, owner, receipts, monkeypatch, outcome):
    body, _ = setup_checkout(client, owner, monkeypatch, 'sandbox' if outcome == 'sandbox' else 'production')
    assert client.post('/api/payments/users/7', headers=owner, json=body).status_code == 200
    monkeypatch.setattr(payments, 'verify_provider_payment', lambda order: outcome if outcome in ('pending', 'declined') else 'paid')
    def activate(*args): raise sas4.SAS4Error('Unconfirmed')
    monkeypatch.setattr(sas4, 'redeem_card', activate)
    payments.process_pending()
    with SessionLocal() as db:
        assert db.scalar(select(rt.Event)) is None


@pytest.mark.parametrize('changed', ['phone', 'username', 'disabled', 'actor_connection', 'owner_connection', 'sender'])
def test_queued_receipts_never_follow_changed_identity_or_settings(client, owner, receipts, changed):
    event_id = enqueue(receipts)
    if changed in ('phone', 'username'):
        receipts[1][changed] = '+9647500000000' if changed == 'phone' else 'other'
    else:
        with SessionLocal() as db:
            selection = db.get(rt.Settings, 1)
            if changed == 'disabled': selection.enabled = False
            if changed == 'actor_connection': db.get(SAS4UserConnection, receipts[0][0]).username = 'changed'
            if changed == 'owner_connection': selection.sas4_username = 'changed'
            if changed == 'sender': selection.sender_id = 'different'
            db.commit()
    assert deliver(event_id)[0] == 'cancelled'
    assert not [c for c in receipts[0][1] if isinstance(c, tuple) and c[0] == 'send']


def test_private_phone_match_is_skipped_without_claiming_no_telegram(client, owner, receipts):
    event_id = enqueue(receipts)
    receipts[0][2].result = NS(users=[])
    status, detail = deliver(event_id)
    assert status == 'skipped' and 'Privacy' in detail


def test_send_timeout_never_retries_and_cannot_repeat_recharge(client, owner, receipts, monkeypatch):
    event_id = enqueue(receipts)
    original = rt.accounts.client_for
    def client_for(state):
        client = original(state)
        class Wrapper:
            async def connect(self): return await client.connect()
            async def disconnect(self): return await client.disconnect()
            async def __call__(self, request):
                result = await client(request)
                if isinstance(request, rt.functions.messages.SendMessageRequest):
                    raise OSError('PRIVATE_TIMEOUT')
                return result
        return Wrapper()
    monkeypatch.setattr(rt.accounts, 'client_for', client_for)
    assert deliver(event_id)[0] == 'unconfirmed'
    assert deliver(event_id)[0] == 'unconfirmed'
    assert len([c for c in receipts[0][1] if isinstance(c, tuple) and c[0] == 'send']) == 1


def test_lookup_failure_can_retry_before_message_attempt(client, owner, receipts):
    event_id = enqueue(receipts)
    receipts[0][2].failure = OSError('PRIVATE_NETWORK')
    assert deliver(event_id)[0] == 'pending'
    clear_rate()
    receipts[0][2].failure = None
    assert deliver(event_id)[0] == 'sent'


def test_recharge_queue_failure_never_turns_success_into_repeat_charge(client, owner, receipts, monkeypatch):
    def broken(*args): raise RuntimeError('database error')
    monkeypatch.setattr(rt, 'enqueue', broken)
    activations = []
    def activate(*args):
        activations.append(1)
        return {'recharged': True}
    monkeypatch.setattr(sas4, 'redeem_card', activate)
    body = {'method': 'card', 'pin': 'PRIVATE_PIN', 'transaction_id': 'c' * 32}
    for _ in range(2):
        assert client.post('/api/integrations/sas4/users/7/recharge', headers=owner, json=body).status_code == 200
    assert len(activations) == 1


def test_settings_owner_only_and_languages(client, owner, receipts):
    _, manager = user(client, owner, 'manager')
    assert client.put(PATH, headers=manager, json={'enabled': True}).status_code == 403
    for language in ('en', 'ar', 'ku'):
        assert client.put(PATH, headers=owner, json={'enabled': True, 'language': language}).status_code == 200
        with SessionLocal() as db:
            assert db.get(rt.Settings, 1).language == language
    assert client.put(PATH, headers=owner, json={'enabled': True, 'timezone': 'invalid'}).status_code == 422


@pytest.mark.parametrize('method', ['card', 'credit'])
@pytest.mark.parametrize('details_fail', [False, True])
@pytest.mark.parametrize('manager_cost', ['2000', '0', None, 'unavailable'])
def test_actual_recharge_receipt_is_safe_and_detail_failure_does_not_repeat_activation(monkeypatch, method, details_fail, manager_cost):
    import httpx
    from types import SimpleNamespace
    monkeypatch.setattr(sas4, 'wire_payload', lambda value: value)
    activations = []
    def transport(request):
        path = request.url.path
        if path.endswith('/login') and request.method == 'POST':
            return httpx.Response(200, json={'token': 'fixture'})
        if path.endswith('/auth'):
            return httpx.Response(200, json={'permissions': ['prm_users_activate', 'prm_users_activate_card', 'prm_users_activate_credit']})
        if path.endswith('/resources/login'):
            return httpx.Response(200, json={'status': 200, 'data': {'site_currency': 'IQD'}})
        if path.endswith('/user/7'):
            if activations and details_fail:
                raise httpx.ReadTimeout('PRIVATE_NETWORK')
            return httpx.Response(200, json={'status': 200, 'data': {'id': 7, 'username': 'customer', 'phone': '+9647501234567',
                'profile_id': 3, 'profile_name': '20 Mbps', 'password': 'PRIVATE_PASSWORD',
                'expiration': '2027-01-01' if activations else '2026-12-01'}})
        if '/activationData/' in path:
            return httpx.Response(200, json={'status': 200, 'data': {'n_required_amount': manager_cost, 'user_price': '2500', 'manager_balance': 'PRIVATE_BALANCE'}})
        assert path.endswith('/user/activate')
        activations.append(1)
        return httpx.Response(200, json={'status': 200})
    data = sas4.CardRecharge(method=method, pin='PRIVATE_PIN_1234', transaction_id='a' * 32,
                            expected_cost=manager_cost if manager_cost in ('2000', '0') else '2000', expected_profile_id=3,
                            expected_expiration='2026-12-01')
    if method == 'credit' and manager_cost in (None, 'unavailable'):
        with pytest.raises(ValueError):
            sas4.redeem_card(SimpleNamespace(**SETTINGS), SETTINGS['password'], 7, data, transport=httpx.MockTransport(transport))
        assert not activations
        return
    result = sas4.redeem_card(SimpleNamespace(**SETTINGS), SETTINGS['password'], 7, data, transport=httpx.MockTransport(transport))
    assert result['recharged'] and len(activations) == 1
    result_text = json.dumps(result)
    assert 'PRIVATE' not in result_text and '+964' not in result_text
    details = result['_notification_receipt']
    if manager_cost in ('2000', '0'):
        assert details['recharge_cost'] == manager_cost and details['currency'] == 'IQD'
    else:
        assert 'recharge_cost' not in details
    assert details.get('expiration') == (None if details_fail else '2027-01-01')
    if method == 'card': assert details['card'] == '••••1234'
    if method == 'credit': assert details['service_price'] == '2500' and details['currency'] == 'IQD'


@pytest.mark.parametrize('language', ['ar', 'ku'])
def test_global_language_applies_to_isp_status_tests_and_pending_receipts(client, owner, receipts, language):
    from test_telegram_account import phone_test_token
    event_id = enqueue(receipts)
    response = client.put(PATH + '/language', headers=owner, json={'language': language})
    assert response.status_code == 200 and response.json()['enabled']
    status = client.get('/api/integrations/customer-telegram/users/7', headers=owner).json()
    assert status['language'] == language and status['language_managed']
    token = phone_test_token(client, owner)
    response = client.post('/api/integrations/telegram-account/users/7/test', headers=owner,
                           json={'test_token': token, 'language': 'en'})
    assert response.status_code == 200
    sends = [c[1] for c in receipts[0][1] if isinstance(c, tuple) and c[0] == 'send']
    assert sends[-1].message == rt.accounts.TEST_MESSAGES[language]
    clear_rate()
    assert deliver(event_id)[0] == 'sent'
    sends = [c[1] for c in receipts[0][1] if isinstance(c, tuple) and c[0] == 'send']
    assert rt.LABELS[language]['title'] in sends[-1].message
    with SessionLocal() as db:
        assert rt.payload(db.get(rt.Event, event_id))['language'] == language


def test_language_saves_while_disabled_without_enabling_or_switching_sender(client, owner, receipts):
    assert client.put(PATH, headers=owner, json={'enabled': False, 'language': 'ku'}).json()['language'] == 'ku'
    _, other = user(client, owner, 'owner', name='other-owner')
    assert client.put(PATH + '/language', headers=other, json={'language': 'ar'}).status_code == 200
    with SessionLocal() as db:
        selection = db.get(rt.Settings, 1)
        assert not selection.enabled and selection.user_id == receipts[0][0] and selection.language == 'ar'
    _, manager = user(client, owner, 'manager')
    assert client.put(PATH + '/language', headers=manager, json={'language': 'en'}).status_code == 403


def test_language_first_save_does_not_enable_automatic_messages(client, owner, receipts):
    with SessionLocal() as db:
        db.delete(db.get(rt.Settings, 1))
        db.commit()
    response = client.put(PATH + '/language', headers=owner, json={'language': 'ku'})
    assert response.status_code == 200 and not response.json()['enabled']
    assert response.json()['language'] == 'ku'
