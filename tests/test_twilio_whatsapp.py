import json
from datetime import timedelta

import httpx
import pytest
from sqlalchemy import select
from airlink import twilio_whatsapp as wa, customer_telegram as ct, sas4, payments
from airlink.db import SessionLocal
from airlink.models import User, SAS4UserConnection, RechargePayment, now
from test_api import user
from test_sas4 import SETTINGS as SAS_SETTINGS

PATH = '/api/integrations/twilio-whatsapp'
ACCOUNT = 'AC' + '1' * 32
TOKEN = 'a' * 32
MESSAGE = 'SM' + 'b' * 32
SENDER = '+15551234567'
CONTENT = {kind: 'HX' + str(index) * 32 for index, kind in enumerate(wa.KINDS, 1)}
CONFIG = {**wa.DEFAULTS, 'account_sid': ACCOUNT, 'from_number': SENDER, 'auth_token': TOKEN,
          **{kind + '_content_sid': sid for kind, sid in CONTENT.items()}}
real_cloud = wa.cloud


@pytest.fixture
def setup(client, owner, monkeypatch):
    client.put('/api/integrations/sas4', headers=owner, json=SAS_SETTINGS)
    record = {'username': 'customer', 'phone': '07501234567', 'enabled': True,
              'expiration': (now() + timedelta(hours=71)).isoformat(), 'password': 'PRIVATE_PASSWORD'}
    monkeypatch.setattr(ct, 'record_for', lambda db, actor, cid: dict(record))
    calls = []
    def cloud(row, method, path, *, body=None, params=None, messaging=False, content=False):
        calls.append((method, path, body, params))
        if method == 'POST':
            return {'sid': MESSAGE, 'account_sid': ACCOUNT, 'status': 'queued', 'error_code': None}
        if content:
            sid = path.split('/')[1]
            if path.endswith('/ApprovalRequests'):
                return {'whatsapp': {'status': 'approved'}}
            kind = next(kind for kind, value in CONTENT.items() if value == sid)
            count = 3 if kind == 'recharge' else 2
            return {'sid': sid, 'account_sid': ACCOUNT, 'language': 'ar',
                    'variables': {str(n): 'Example' for n in range(1, count + 1)},
                    'types': {'twilio/text': {'body': ' '.join('{{' + str(n) + '}}' for n in range(1, count + 1))}}}
        if messaging:
            return {'sid': path.split('/')[-1], 'account_sid': ACCOUNT}
        return {'sid': ACCOUNT, 'status': 'active'}
    monkeypatch.setattr(wa, 'cloud', cloud)
    assert client.put(PATH, headers=owner, json=CONFIG).status_code == 200
    assert client.post(PATH + '/check', headers=owner).status_code == 200
    enabled = {**CONFIG, 'auth_token': '', **{kind: True for kind in wa.KINDS}}
    assert client.put(PATH, headers=owner, json=enabled).status_code == 200
    assert client.put(PATH + '/users/7', headers=owner, json={'enabled': True}).status_code == 200
    return record, calls, enabled


def enqueue(record, method='card', actor_id=None, reference='transaction-1'):
    with SessionLocal() as db:
        actor = db.get(User, actor_id) if actor_id else db.scalar(select(User).where(User.role == 'owner'))
        ct.activation(db, actor, 7, method, reference,
            {'username': record['username'], 'phone_hash': ct.phone_hash(record), 'expiration': record['expiration'], 'card': 'PRIVATE_PIN'})
        db.commit()
        return db.scalar(select(wa.Event))


def deliver(event_id):
    with SessionLocal() as db:
        event = db.get(wa.Event, event_id)
        wa.deliver(db, event)
        return event.status, event.detail


def sent(setup):
    return [call for call in setup[1] if call[0] == 'POST']


def test_setup_checks_sender_without_sending_and_encrypts_token(client, owner, setup):
    data = client.get(PATH, headers=owner)
    assert data.status_code == 200 and data.json()['verified_at']
    assert TOKEN not in data.text and 'auth_token' not in data.json()
    assert not sent(setup)
    assert len(setup[1]) == 7
    with SessionLocal() as db:
        row = db.get(wa.Settings, 1)
        assert TOKEN not in row.encrypted_token
        assert wa.cipher().decrypt(row.encrypted_token.encode()).decode() == TOKEN


@pytest.mark.parametrize('method', ['card', 'credit', 'extend', 'fib', 'fastpay'])
def test_confirmed_recharges_once_with_correct_recipient_and_text(client, owner, setup, method):
    event = enqueue(setup[0], method)
    assert enqueue(setup[0], method).id == event.id
    assert deliver(event.id)[0] == 'accepted'
    assert deliver(event.id)[0] == 'accepted'
    assert len(sent(setup)) == 1
    body = sent(setup)[0][2]
    assert body['To'] == 'whatsapp:+9647501234567' and body['From'] == 'whatsapp:' + SENDER
    assert 'MessagingServiceSid' not in body
    assert body['ContentSid'] == CONTENT['recharge']
    assert json.loads(body['ContentVariables'])['1'] == 'customer'
    assert json.loads(body['ContentVariables'])['3'] == 'transaction-1'
    assert 'Body' not in body
    assert 'PRIVATE' not in json.dumps(body)
    with SessionLocal() as db:
        assert 'customer' not in db.get(wa.Event, event.id).encrypted_payload


@pytest.mark.parametrize('hours,kind', [(73,None), (71,'expiry_3days'), (49,'expiry_3days'), (47,None),
                                      (1,None), (-1,'expired'), (-23,'expired'), (-25,None)])
def test_expiry_once_per_date(client, owner, setup, hours, kind):
    setup[0]['expiration'] = (now() + timedelta(hours=hours)).isoformat()
    with SessionLocal() as db:
        row = db.get(wa.Settings, 1)
        wa.scan_expiry(db, row)
        pref = db.get(wa.Customer, (row.user_id, 7))
        pref.next_check = now() - timedelta(seconds=1)
        db.commit()
        wa.scan_expiry(db, row)
        events = db.scalars(select(wa.Event)).all()
        assert len(events) == int(kind is not None)
        if kind:
            assert events[0].kind == kind
            wa.deliver(db, events[0])
            assert events[0].status == 'accepted'
            wa.deliver(db, events[0])
            assert len(sent(setup)) == 1


@pytest.mark.parametrize('change', ['renewed', 'disabled', 'late', 'phone', 'username', 'opt_out', 'settings', 'owner_disabled', 'actor_scope'])
def test_stale_messages_cancelled(client, owner, setup, monkeypatch, change):
    with SessionLocal() as db:
        row = db.get(wa.Settings, 1)
        wa.scan_expiry(db, row)
        event = db.scalar(select(wa.Event))
        if change == 'renewed': setup[0]['expiration'] = (now() + timedelta(days=30)).isoformat()
        if change == 'disabled': setup[0]['enabled'] = False
        if change == 'late': monkeypatch.setattr(wa, 'now', lambda: now() + timedelta(days=2))
        if change == 'phone': setup[0]['phone'] = '+9647501234568'
        if change == 'username': setup[0]['username'] = 'replacement'
        if change == 'opt_out': db.get(wa.Customer, (row.user_id, 7)).enabled = False
        if change == 'settings': row.config = {**row.config, 'expiry_3days': False}
        if change == 'owner_disabled': db.get(User, row.user_id).active = False
        if change == 'actor_scope': db.get(SAS4UserConnection, row.user_id).username = 'changed'
        db.commit()
        wa.deliver(db, event)
        assert event.status == 'cancelled'
    assert not sent(setup)


def test_no_enrollment_or_missing_phone_never_sends(client, owner, setup):
    assert client.put(PATH + '/users/7', headers=owner, json={'enabled': False}).status_code == 200
    assert enqueue(setup[0]) is None
    setup[0]['phone'] = ''
    assert client.put(PATH + '/users/7', headers=owner, json={'enabled': True}).status_code == 422
    assert not sent(setup)


def test_phone_change_requires_new_permission_and_hides_old_history(client, owner, setup):
    event = enqueue(setup[0])
    deliver(event.id)
    setup[0]['phone'] = '+9647501234568'
    result = client.get(PATH + '/users/7', headers=owner).json()
    assert not result['enabled'] and not result['events']
    with SessionLocal() as db:
        wa.scan_expiry(db, db.get(wa.Settings, 1))
        assert not db.scalar(select(wa.Customer)).enabled


def test_twilio_cooldown_pauses_without_duplicate_send(client, owner, setup, monkeypatch):
    event = enqueue(setup[0])
    attempts = []
    def limited(*args, **kwargs):
        attempts.append(1)
        raise wa.CloudError('Twilio WhatsApp requested a cooldown.', retry_after=300)
    monkeypatch.setattr(wa, 'cloud', limited)
    assert deliver(event.id)[0] == 'pending'
    assert deliver(event.id)[0] == 'pending'
    assert len(attempts) == 1
    with SessionLocal() as db:
        assert wa.aware(db.get(wa.Settings, 1).retry_at) > now()
    assert client.get(PATH, headers=owner).json()['retry_at']


@pytest.mark.parametrize('ambiguous,status', [(True,'unconfirmed'), (False,'failed')])
def test_failed_and_ambiguous_sends_never_repeated(client, owner, setup, monkeypatch, ambiguous, status):
    event = enqueue(setup[0])
    attempts = []
    def failed(*args, **kwargs):
        attempts.append(1)
        raise wa.CloudError('Provider failure', ambiguous=ambiguous)
    monkeypatch.setattr(wa, 'cloud', failed)
    assert deliver(event.id)[0] == status
    deliver(event.id)
    assert len(attempts) == 1


def test_sas4_failure_before_send_retries_and_queue_failure_does_not_break_recharge(client, owner, setup, monkeypatch):
    event = enqueue(setup[0])
    def failed(*args, **kwargs): raise RuntimeError('PRIVATE_PROVIDER_ERROR')
    monkeypatch.setattr(ct, 'record_for', failed)
    assert deliver(event.id)[0] == 'pending'
    assert not sent(setup)
    monkeypatch.setattr(wa, 'enqueue', failed)
    # Confirmed recharge notification entrypoint must absorb a Twilio WhatsApp failure.
    enqueue(setup[0], reference='another-transaction')


def test_permissions_and_no_secret_echo(client, owner, setup):
    _, viewer = user(client, owner, 'viewer', name='whatsapp-viewer')
    _, manager = user(client, owner, 'manager', name='whatsapp-manager')
    for headers in (viewer, manager):
        assert client.get(PATH, headers=headers).status_code == 403
        assert client.put(PATH, headers=headers, json=CONFIG).status_code == 403
        assert client.post(PATH + '/check', headers=headers).status_code == 403
        assert client.delete(PATH, headers=headers).status_code == 403
    assert client.get(PATH + '/users/7', headers=viewer).status_code == 403
    response = client.put(PATH, headers=owner, json={**CONFIG, 'auth_token': TOKEN + '\n', 'timezone': 'INVALID'})
    assert response.status_code == 422 and TOKEN not in response.text


@pytest.mark.parametrize('bad', ['inactive', 'account', 'unapproved', 'template_account', 'variables', 'rich_template'])
def test_bad_account_or_templates_not_verified(client, owner, setup, monkeypatch, bad):
    original = wa.cloud
    def cloud(row, method, path, **kwargs):
        result = original(row, method, path, **kwargs)
        if path.startswith('Accounts/'):
            if bad == 'inactive': result['status'] = 'suspended'
            if bad == 'account': result['sid'] = 'AC' + '2' * 32
        elif path.endswith('/ApprovalRequests'):
            if bad == 'unapproved': result['whatsapp']['status'] = 'pending'
        elif kwargs.get('content'):
            if bad == 'template_account': result['account_sid'] = 'AC' + '2' * 32
            if bad == 'variables': result['variables'] = {'1': 'Example'}
            if bad == 'rich_template': result['types']['twilio/card'] = {'title': 'Card'}
        return result
    monkeypatch.setattr(wa, 'cloud', cloud)
    result = client.post(PATH + '/check', headers=owner)
    assert result.status_code == 502
    assert client.get(PATH, headers=owner).json()['verified_at'] is None
    assert not sent(setup)


def test_changed_config_requires_recheck_disconnect_cancels_pending(client, owner, setup):
    event = enqueue(setup[0])
    assert client.put(PATH, headers=owner, json={**setup[2], 'from_number': '+15559999999'}).status_code == 409
    assert client.delete(PATH, headers=owner).status_code == 200
    with SessionLocal() as db:
        assert db.get(wa.Settings, 1) is None
        assert db.scalar(select(wa.Customer)) is None
        assert db.get(wa.Event, event.id).status == 'cancelled'
    assert not sent(setup)


@pytest.mark.parametrize('method', ['card', 'credit', 'extend', 'fib', 'fastpay'])
def test_actual_confirmed_recharge_hooks_queue_from_managers(client, owner, setup, monkeypatch, method):
    mid, manager = user(client, owner, 'manager', name='wa-recharge-manager')
    if method == 'fib':
        assert client.put('/api/users/' + mid + '/sections', headers=owner, json={
            'sections': ['isp_card', 'fib_recharge'],
            'editable_sections': ['isp_card', 'fib_recharge'], 'deletable_sections': []}).status_code == 200
    client.put('/api/integrations/sas4', headers=manager, json=SAS_SETTINGS)
    calls = []
    def redeem(*args, **kwargs):
        calls.append(1)
        return {'recharged': True, '_notification_receipt': {'username': setup[0]['username'],
            'phone_hash': ct.phone_hash(setup[0]), 'expiration': setup[0]['expiration']}}
    monkeypatch.setattr(sas4, 'redeem_card', redeem)
    if method in ('fib', 'fastpay'):
        with SessionLocal() as db:
            db.add(RechargePayment(id='b' * 32, user_id=mid, sas4_user_id=7, sas4_username=SAS_SETTINGS['username'],
                provider=method, environment='production', amount='2500', currency='IQD', status='pending',
                encrypted_credentials=ct.cipher().encrypt(b'{}').decode(), provider_id='fixture',
                quote={'manager_cost': '2000', 'profile_id': 3, 'expiration': '2026-11-01'}))
            db.commit()
        monkeypatch.setattr(payments, 'verify_provider_payment', lambda order: 'paid')
        payments.process_pending()
        payments.process_pending()
    else:
        for _ in range(2):
            result = client.post('/api/integrations/sas4/users/7/recharge', headers=manager,
                json={'method': method, 'pin': 'PRIVATE_PIN', 'transaction_id': 'b' * 32,
                      'expected_cost': '0', 'expected_profile_id': 3, 'extension_id': 1})
            assert result.status_code == 200
    assert len(calls) == 1
    with SessionLocal() as db:
        events = db.scalars(select(wa.Event)).all()
        assert len(events) == 1 and events[0].actor_id == mid
        wa.deliver(db, events[0])
        assert events[0].status == 'accepted'
    assert len(sent(setup)) == 1


@pytest.mark.parametrize('status,ambiguous,retry', [(201,False,False), (401,False,False), (429,False,True), (503,True,False)])
def test_cloud_transport_fixed_origin_redacted_errors(client, owner, setup, monkeypatch, status, ambiguous, retry):
    import base64
    from urllib.parse import parse_qs
    captured = []
    real_client = httpx.Client
    response = {'sid': MESSAGE, 'account_sid': ACCOUNT, 'status': 'queued'} if status == 201 else {'message': TOKEN}
    def handler(request):
        captured.append(request)
        return httpx.Response(status, json=response, headers={'Retry-After':'120'})
    monkeypatch.setattr(wa.httpx, 'Client', lambda **kwargs: real_client(**kwargs, transport=httpx.MockTransport(handler)))
    with SessionLocal() as db:
        row = db.get(wa.Settings, 1)
        if status == 201:
            assert real_cloud(row, 'POST', wa.account_path(row) + '/Messages.json', body={'To': 'whatsapp:+9647501234567', 'ContentSid': CONTENT['recharge']}) == response
        else:
            with pytest.raises(wa.CloudError) as caught:
                real_cloud(row, 'POST', wa.account_path(row) + '/Messages.json', body={'To': 'whatsapp:+9647501234567', 'ContentSid': CONTENT['recharge']})
            assert TOKEN not in caught.value.detail
            assert caught.value.ambiguous == ambiguous
            assert bool(caught.value.retry_after) == retry
    assert captured[0].url.host == 'api.twilio.com'
    assert captured[0].url.path == '/2010-04-01/Accounts/' + ACCOUNT + '/Messages.json'
    assert captured[0].headers['authorization'] == 'Basic ' + base64.b64encode((ACCOUNT + ':' + TOKEN).encode()).decode()
    assert parse_qs(captured[0].content.decode()) == {'To': ['whatsapp:+9647501234567'], 'ContentSid': [CONTENT['recharge']]}
    assert TOKEN not in str(captured[0].url)


def test_saving_unchanged_settings_preserves_pending_receipt(client, owner, setup):
    event = enqueue(setup[0])
    assert client.put(PATH, headers=owner, json=setup[2]).status_code == 200
    assert deliver(event.id)[0] == 'accepted'


def test_background_worker_scans_sends_once_and_obeys_shared_lock(client, owner, setup):
    from airlink import api
    lock = api.cache.lock('twilio_whatsapp:operations', timeout=300, blocking=False)
    assert lock.acquire(blocking=False)
    with pytest.raises(wa.HTTPException) as caught:
        wa.tick()
    assert caught.value.status_code == 409
    lock.release()
    wa.tick()
    wa.tick()
    assert len(sent(setup)) == 1
    with SessionLocal() as db:
        event = db.scalar(select(wa.Event))
        assert event.kind == 'expiry_3days' and event.status == 'accepted'


def test_transport_timeout_leaves_send_unconfirmed(client, owner, setup, monkeypatch):
    event = enqueue(setup[0])
    calls = []
    real_client = httpx.Client
    def handler(request):
        calls.append(request)
        raise httpx.ReadTimeout('PRIVATE_PROVIDER_BODY', request=request)
    monkeypatch.setattr(wa.httpx, 'Client', lambda **kwargs: real_client(**kwargs, transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(wa, 'cloud', real_cloud)
    status, detail = deliver(event.id)
    assert status == 'unconfirmed' and 'PRIVATE' not in detail
    deliver(event.id)
    assert len(calls) == 1


@pytest.mark.parametrize('status,expected', [('delivered', 'delivered'), ('read', 'delivered'), ('sent', 'accepted'), ('undelivered', 'failed'), ('failed', 'failed')])
def test_delivery_receipts_do_not_resend(client, owner, setup, monkeypatch, status, expected):
    event = enqueue(setup[0])
    assert deliver(event.id)[0] == 'accepted'
    reads = []
    def receipt(row, method, path, **kwargs):
        assert method == 'GET' and path.endswith('/Messages/' + MESSAGE + '.json')
        reads.append(path)
        return {'sid': MESSAGE, 'account_sid': ACCOUNT, 'status': status, 'error_message': TOKEN}
    monkeypatch.setattr(wa, 'cloud', receipt)
    with SessionLocal() as db:
        event = db.get(wa.Event, event.id)
        wa.refresh_delivery(db, db.get(wa.Settings, 1), event)
        assert event.status == expected and TOKEN not in event.detail
        wa.deliver(db, event)
    assert len(reads) == 1 and len(sent(setup)) == 1


def test_receipt_after_sender_change_never_uses_new_credentials(client, owner, setup, monkeypatch):
    event = enqueue(setup[0]); deliver(event.id)
    with SessionLocal() as db:
        row = db.get(wa.Settings, 1)
        row.version = 'changed'
        monkeypatch.setattr(wa, 'cloud', lambda *a, **k: pytest.fail('Do not use another sender configuration'))
        event = db.get(wa.Event, event.id)
        wa.refresh_delivery(db, row, event)
        assert event.status == 'accepted'


def test_messaging_service_sender_and_unicode_variables(client, owner, setup):
    service = 'MG' + 'c' * 32
    config = {**CONFIG, 'from_number': '', 'messaging_service_sid': service}
    assert client.put(PATH, headers=owner, json=config).status_code == 200
    assert client.post(PATH + '/check', headers=owner).status_code == 200
    config.update(auth_token='', recharge=True)
    assert client.put(PATH, headers=owner, json=config).status_code == 200
    setup[0]['username'] = 'سڵاو\nکڕیار'
    assert client.put(PATH + '/users/7', headers=owner, json={'enabled': True}).status_code == 200
    event = enqueue(setup[0]); assert deliver(event.id)[0] == 'accepted'
    body = sent(setup)[0][2]
    assert body['MessagingServiceSid'] == service and 'From' not in body and 'Body' not in body
    assert json.loads(body['ContentVariables'])['1'] == 'سڵاو کڕیار'
    assert body['To'] == 'whatsapp:+9647501234567'


@pytest.mark.parametrize('changes', [
    {'account_sid': 'https://malicious.invalid'}, {'auth_token': 'secret\n'},
    {'from_number': 'whatsapp:+15551234567'}, {'messaging_service_sid': 'MG' + 'c' * 32},
    {'from_number': ''}, {'recharge_content_sid': 'not-an-HX-SID'},
    {'expiry_3days_content_sid': ''}, {'expired_content_sid': 'https://malicious.invalid'},
    {'recharge_message': 'No free-form fallback'},
])
def test_invalid_settings_redacted(client, owner, setup, changes):
    result = client.put(PATH, headers=owner, json={**CONFIG, **changes})
    assert result.status_code == 422 and TOKEN not in result.text
    assert not sent(setup)


def test_account_change_requires_new_token_and_notifications_start_off(client, owner, setup):
    assert client.put(PATH, headers=owner, json={**CONFIG, 'account_sid': 'AC'+'2'*32, 'auth_token': ''}).status_code == 422
    assert client.put(PATH, headers=owner, json={**CONFIG, 'recharge': True}).status_code == 409
    assert client.get('/api/integrations/whatsapp', headers=owner).status_code == 404


@pytest.mark.parametrize('response,expected', [
    ({'sid': 'wrong', 'account_sid': ACCOUNT, 'status': 'queued'}, 'unconfirmed'),
    ({'sid': MESSAGE, 'account_sid': 'AC'+'2'*32, 'status': 'queued'}, 'unconfirmed'),
    ({'sid': MESSAGE, 'account_sid': ACCOUNT, 'status': 'failed'}, 'failed'),
    ({'sid': MESSAGE, 'account_sid': ACCOUNT, 'status': 'unrecognized'}, 'unconfirmed'),
])
def test_unconfirmed_or_failed_provider_submission_not_repeated(client, owner, setup, monkeypatch, response, expected):
    event = enqueue(setup[0]); calls = []
    def send(*args, **kwargs):
        calls.append(1)
        return response
    monkeypatch.setattr(wa, 'cloud', send)
    assert deliver(event.id)[0] == expected
    deliver(event.id)
    assert calls == [1]


def test_whatsapp_delegation_and_immediate_revocation(client, owner, setup):
    mid, manager = user(client, owner, 'manager', name='twilio-whatsapp-manager')
    client.put('/api/integrations/sas4', headers=manager, json=SAS_SETTINGS)
    policy = {'sections': ['isp_card', 'whatsapp'], 'editable_sections': ['isp_card'], 'deletable_sections': []}
    assert client.put('/api/users/' + mid + '/sections', headers=owner, json=policy).status_code == 200
    assert client.get(PATH, headers=manager).status_code == 200
    assert client.put(PATH, headers=manager, json=CONFIG).status_code == 403
    policy['editable_sections'].append('whatsapp')
    assert client.put('/api/users/' + mid + '/sections', headers=owner, json=policy).status_code == 200
    assert client.put(PATH, headers=manager, json=CONFIG).status_code == 200
    assert client.post(PATH + '/check', headers=manager).status_code == 200
    assert client.delete(PATH, headers=manager).status_code == 403
    policy['editable_sections'] = ['isp_card']
    assert client.put('/api/users/' + mid + '/sections', headers=owner, json=policy).status_code == 200
    assert client.get(PATH, headers=owner).json()['account_ready'] is False


@pytest.mark.parametrize('option,path,host', [
    ('content', 'Content/' + CONTENT['recharge'] + '/ApprovalRequests', 'content.twilio.com'),
    ('messaging', 'Services/MG' + 'c' * 32, 'messaging.twilio.com'),
])
def test_provider_checks_use_fixed_twilio_origins(client, owner, setup, monkeypatch, option, path, host):
    requests = []
    real_client = httpx.Client
    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={'checked': True})
    monkeypatch.setattr(wa.httpx, 'Client', lambda **kwargs: real_client(**kwargs, transport=httpx.MockTransport(handler)))
    with SessionLocal() as db:
        assert real_cloud(db.get(wa.Settings, 1), 'GET', path, **{option: True}) == {'checked': True}
    assert requests[0].url.host == host and requests[0].url.path == '/v1/' + path
    assert requests[0].method == 'GET' and TOKEN not in str(requests[0].url)
