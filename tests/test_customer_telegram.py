import hashlib
from datetime import timedelta
from urllib.parse import urlparse, parse_qs
import pytest
from sqlalchemy import select
from airlink import customer_telegram as ct, sas4, payments
from airlink.db import SessionLocal
from airlink.models import User, UserSectionEdits, SAS4UserConnection, now
from airlink.security import cipher
from test_api import user
from test_sas4 import SETTINGS
from test_payments import setup_checkout

PATH = '/api/integrations/customer-telegram'
TOKEN = '456789:PRIVATE_customer_bot'


@pytest.fixture
def customer(client, owner, monkeypatch):
    actor = client.get('/api/auth/me', headers=owner).json()['id']
    client.put('/api/integrations/sas4', headers=owner, json=SETTINGS)
    record = {'id': 7, 'username': 'customer', 'expiration': (now() + timedelta(days=2, hours=23)).isoformat(),
              'phone': '+9647501234567', 'password': 'PRIVATE-PASSWORD'}
    calls, updates = [], []
    def api(bot, method, body):
        calls.append((method, body))
        if method == 'getMe': return {'id': 456789, 'username': 'AirLinkTestBot', 'is_bot': True}
        if method == 'getWebhookInfo': return {'url': ''}
        if method == 'getUpdates': return list(updates)
        return {'message_id': 123}
    monkeypatch.setattr(ct, 'api', api)
    monkeypatch.setattr(ct, 'record_for', lambda db, user, cid: dict(record))
    result = client.put(PATH, headers=owner, json={'bot_token': TOKEN})
    assert result.status_code == 200, result.text
    assert TOKEN not in result.text
    with SessionLocal() as db:
        assert TOKEN not in db.get(ct.Bot, actor).encrypted_token
    return actor, record, calls, updates


def start(client, owner, customer, language='en'):
    actor, record, calls, updates = customer
    result = client.post(PATH + '/users/7/link', headers=owner, json={'language': language})
    assert result.status_code == 200, result.text
    token = parse_qs(urlparse(result.json()['url']).query)['start'][0]
    updates[:] = [{'update_id': 1, 'message': {'text': '/start ' + token,
        'chat': {'id': 789, 'type': 'private'}, 'from': {'id': 789, 'is_bot': False}}}]
    with SessionLocal() as db:
        link = db.get(ct.Link, (actor, 7))
        assert link.token_hash == hashlib.sha256(token.encode()).hexdigest()
        ct.poll_bot(db, db.get(ct.Bot, actor))
        assert link.chat_id is None and link.pending_chat_id == '789'
        updates[:] = [{'update_id': 2, 'message': {'contact': {'user_id': 789, 'phone_number': record['phone']},
            'chat': {'id': 789, 'type': 'private'}, 'from': {'id': 789, 'is_bot': False}}}]
        ct.poll_bot(db, db.get(ct.Bot, actor))
        assert link.phone_verified_at is not None
    # Existing notification assertions count confirmations, not the enrollment prompt.
    calls[:] = [call for call in calls if not call[1].get('reply_markup', {}).get('keyboard')]
    return token


def test_link_single_use_private_only_and_stop_cancels_delivery(client, owner, customer):
    actor, _, calls, updates = customer
    token = start(client, owner, customer)
    assert client.get(PATH + '/users/7', headers=owner).json()['linked']
    assert client.post(PATH + '/users/7/link', headers=owner, json={}).status_code == 409
    with SessionLocal() as db:
        link = db.get(ct.Link, (actor, 7))
        assert link.chat_id == '789' and link.token_hash is None
        ct.poll_bot(db, db.get(ct.Bot, actor))
        assert len(db.scalars(select(ct.Event)).all()) == 1
        ct.deliver(db, db.scalar(select(ct.Event)))
        assert db.scalar(select(ct.Event)).status == 'sent'
        ct.enqueue(db, actor, 7, 'card', 'transaction')
        db.commit()
        updates[:] = [{'update_id': 3, 'message': {'text': '/stop', 'chat': {'id': 789, 'type': 'private'}, 'from': {'id': 789, 'is_bot': False}}}]
        ct.poll_bot(db, db.get(ct.Bot, actor))
        ct.deliver(db, db.scalar(select(ct.Event).where(ct.Event.kind == 'card')))
        assert db.scalar(select(ct.Event).where(ct.Event.kind == 'card')).status == 'cancelled'
    assert len([c for c in calls if c[0] == 'sendMessage']) == 1
    assert not client.get(PATH + '/users/7', headers=owner).json()['linked']


@pytest.mark.parametrize('invalid', ['group', 'expired', 'wrong_account', 'replaced'])
def test_invalid_links_never_bind(client, owner, customer, invalid):
    actor, _, calls, updates = customer
    result = client.post(PATH + '/users/7/link', headers=owner, json={}).json()
    token = parse_qs(urlparse(result['url']).query)['start'][0]
    if invalid == 'replaced':
        client.post(PATH + '/users/7/link', headers=owner, json={})
    updates[:] = [{'update_id': 1, 'message': {'text': '/start ' + token,
        'chat': {'id': 789, 'type': 'group' if invalid == 'group' else 'private'}, 'from': {'id': 789, 'is_bot': False}}}]
    with SessionLocal() as db:
        link, bot = db.get(ct.Link, (actor, 7)), db.get(ct.Bot, actor)
        if invalid == 'expired': link.token_expires = now() - timedelta(seconds=1)
        if invalid == 'wrong_account': link.customer_username = 'someone_else'
        db.commit()
        ct.poll_bot(db, bot)
        assert link.chat_id is None and db.scalar(select(ct.Event)) is None
    assert not [c for c in calls if c[0] == 'sendMessage']


@pytest.mark.parametrize('hours,queued', [(73, False), (71, True), (48, False), (0, False), (-1, False)])
def test_expiry_window_dedup_and_renewal_recheck(client, owner, customer, hours, queued):
    actor, record, calls, updates = customer
    start(client, owner, customer)
    record['expiration'] = (now() + timedelta(hours=hours)).isoformat()
    with SessionLocal() as db:
        bot, link = db.get(ct.Bot, actor), db.get(ct.Link, (actor, 7))
        ct.check_expiry(db, bot, link, record)
        db.commit()
        ct.check_expiry(db, bot, link, record)
        db.commit()
        events = db.scalars(select(ct.Event).where(ct.Event.kind == 'expiry')).all()
        assert len(events) == int(queued)
        if queued:
            record['expiration'] = (now() + timedelta(days=32)).isoformat()
            ct.deliver(db, events[0])
            assert events[0].status == 'cancelled'
    assert not [c for c in calls if c[0] == 'sendMessage']


@pytest.mark.parametrize('method', ['card', 'credit', 'extend'])
def test_confirmed_recharge_only_enqueues_once_no_pin(client, owner, customer, monkeypatch, method):
    actor, _, calls, _ = customer
    start(client, owner, customer)
    monkeypatch.setattr(sas4, 'redeem_card', lambda *a, **kw: {'recharged': True})
    body = {'method': method, 'pin': 'PRIVATE-PIN', 'transaction_id': 'c' * 32,
            'expected_cost': '0', 'expected_profile_id': 1, 'extension_id': 1}
    for _ in range(2):
        result = client.post('/api/integrations/sas4/users/7/recharge', headers=owner, json=body)
        assert result.status_code == 200, result.text
    with SessionLocal() as db:
        events = db.scalars(select(ct.Event).where(ct.Event.kind == method)).all()
        assert len(events) == 1
        ct.deliver(db, events[0])
        assert events[0].status == 'sent'
    sent = str([body for method, body in calls if method == 'sendMessage'])
    assert 'PRIVATE' not in sent and 'customer' in sent


@pytest.mark.parametrize('provider', ['fib', 'fastpay'])
@pytest.mark.parametrize('outcome', ['paid', 'pending', 'declined', 'unknown', 'sandbox'])
def test_bank_confirmation_controls_customer_notification(client, owner, customer, monkeypatch, provider, outcome):
    actor, _, _, _ = customer
    start(client, owner, customer)
    environment = 'sandbox' if outcome == 'sandbox' else 'production'
    if provider == 'fib':
        from test_fib_cards import checkout
        body, _ = checkout(client, owner, monkeypatch, environment)
    else:
        body, _ = setup_checkout(client, owner, monkeypatch, environment, provider=provider)
    assert client.post('/api/payments/users/7', headers=owner, json=body).status_code == 200
    monkeypatch.setattr(payments, 'verify_provider_payment', lambda order: outcome if outcome in ('pending', 'declined') else 'paid')
    def activate(*a, **kw):
        if outcome == 'unknown': raise sas4.SAS4Error('Unconfirmed')
        return {'recharged': True}
    monkeypatch.setattr(sas4, 'redeem_card', activate)
    payments.process_pending()
    payments.process_pending()
    with SessionLocal() as db:
        assert len(db.scalars(select(ct.Event).where(ct.Event.kind == provider)).all()) == int(outcome == 'paid')


def test_permissions_account_change_and_retries(client, owner, customer, monkeypatch):
    actor, record, calls, _ = customer
    start(client, owner, customer, 'ar')
    _, viewer = user(client, owner, 'viewer', 'no-customer-config')
    assert client.put(PATH, headers=viewer, json={'bot_token': TOKEN}).status_code == 403
    mid, manager = user(client, owner, 'manager', 'customer-manager')
    shared = client.get(PATH, headers=manager).json()
    assert shared['configured'] is True and shared['can_manage'] is False
    assert shared['username'] == 'AirLinkTestBot' and TOKEN not in str(shared)
    client.put('/api/integrations/sas4', headers=manager, json=SETTINGS)
    assert client.put(PATH, headers=manager, json={'bot_token': TOKEN}).status_code == 403
    with SessionLocal() as db:
        db.add(UserSectionEdits(user_id=mid, sections=[])); db.commit()
    assert client.post(PATH + '/users/7/link', headers=manager, json={}).status_code == 403
    with SessionLocal() as db:
        event = db.scalar(select(ct.Event))
        original = ct.api
        def fail(*args): raise RuntimeError('PRIVATE-token-in-exception')
        monkeypatch.setattr(ct, 'api', fail)
        for _ in range(5): ct.deliver(db, event)
        assert event.status == 'failed' and event.attempts == 5
        assert 'PRIVATE' not in db.get(ct.Link, (actor, 7)).last_error
        monkeypatch.setattr(ct, 'api', original)
        ct.enqueue(db, actor, 7, 'extend', 'other')
        db.commit()
        db.get(SAS4UserConnection, actor).username = 'different-sas4-account'
        db.commit()
        ct.deliver(db, db.scalar(select(ct.Event).where(ct.Event.kind == 'extend')))
        assert db.scalar(select(ct.Event).where(ct.Event.kind == 'extend')).status == 'cancelled'


def test_worker_polls_expiry_and_delivers_without_browser(client, owner, customer):
    actor, _, calls, updates = customer
    start(client, owner, customer)
    ct.tick()
    with SessionLocal() as db:
        assert len(db.scalars(select(ct.Event).where(ct.Event.kind == 'expiry')).all()) == 1
        assert db.scalar(select(ct.Event).where(ct.Event.kind == 'linked')).status == 'sent'
    ct.tick()
    assert len([c for c in calls if c[0] == 'sendMessage']) == 2


def test_timezone_validation_and_token_errors_are_redacted(client, owner, customer):
    assert ct.expiry_time('2026-12-01 00:00:00', 'Asia/Baghdad').utcoffset() == timedelta(hours=3)
    assert ct.expiry_time('broken', 'Asia/Baghdad') is None
    result = client.put(PATH, headers=owner, json={'bot_token': 'PRIVATE INVALID TOKEN'})
    assert result.status_code == 422 and 'PRIVATE' not in result.text
    assert client.put(PATH, headers=owner, json={'timezone': 'Invalid/Timezone'}).status_code == 422
    assert client.put('/api/integrations/telegram', headers=owner, json={'bot_token': TOKEN, 'chat_id': '123'}).status_code == 409


def test_disabling_or_replacing_bot_drops_pending_customer_events(client, owner, customer):
    actor, _, _, _ = customer
    start(client, owner, customer)
    assert client.put(PATH, headers=owner, json={'enabled': False}).status_code == 200
    with SessionLocal() as db:
        assert db.scalar(select(ct.Event)) is None
        ct.enqueue(db, actor, 7, 'card', 'disabled')
        db.commit()
        assert db.scalar(select(ct.Event)) is None


def test_customer_notification_migration_preserves_existing_data(tmp_path):
    import importlib.util
    from pathlib import Path
    from sqlalchemy import create_engine, text, inspect
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    spec = importlib.util.spec_from_file_location('customer_telegram_migration', Path(__file__).resolve().parents[1] /
        'database/versions/b38cf705196f_customer_telegram.py')
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine('sqlite:///' + str(tmp_path / 'migration.sqlite'))
    with engine.begin() as connection:
        connection.execute(text('CREATE TABLE users (id VARCHAR(36) PRIMARY KEY)'))
        connection.execute(text("INSERT INTO users VALUES ('existing-owner')"))
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        for model in [ct.Bot, ct.Link, ct.Event]:
            columns = {c['name'] for c in inspect(connection).get_columns(model.__tablename__)}
            expected = set(model.__table__.columns.keys())
            if model is ct.Link:
                expected -= {'pending_chat_id', 'phone_hash', 'phone_verified_at'}
            assert columns == expected
        assert connection.execute(text('SELECT id FROM users')).scalar_one() == 'existing-owner'
        migration.downgrade()
        assert inspect(connection).get_table_names() == ['users']
        migration.upgrade()
        assert connection.execute(text('SELECT id FROM users')).scalar_one() == 'existing-owner'


def test_revoked_access_and_old_recipient_never_receive_pending_events(client, owner, customer):
    actor, record, calls, _ = customer
    start(client, owner, customer)
    with SessionLocal() as db:
        ct.enqueue(db, actor, 7, 'credit', 'revoked')
        db.commit()
        db.get(User, actor).active = False
        db.commit()
        event = db.scalar(select(ct.Event).where(ct.Event.kind == 'credit'))
        ct.deliver(db, event)
        assert event.status == 'cancelled'
        db.get(User, actor).active = True
        db.get(ct.Link, (actor, 7)).version = 'replacement-recipient'
        db.commit()
        ct.deliver(db, db.scalar(select(ct.Event).where(ct.Event.kind == 'linked')))
        assert db.scalar(select(ct.Event).where(ct.Event.kind == 'linked')).status == 'cancelled'
    assert not [c for c in calls if c[0] == 'sendMessage']


def test_queue_failure_does_not_replay_confirmed_activation(client, owner, customer, monkeypatch):
    start(client, owner, customer)
    activations = []
    def activate(*args):
        activations.append(True)
        return {'recharged': True}
    def fail(*args): raise RuntimeError('queue unavailable')
    monkeypatch.setattr(sas4, 'redeem_card', activate)
    monkeypatch.setattr(ct, 'enqueue', fail)
    for _ in range(2):
        result = client.post('/api/integrations/sas4/users/7/recharge', headers=owner,
            json={'pin': 'PRIVATE-PIN', 'transaction_id': 'd' * 32})
        assert result.status_code == 200
    assert len(activations) == 1


def test_disable_works_during_outage_and_existing_webhook_is_not_removed(client, owner, customer, monkeypatch):
    actor, _, calls, _ = customer
    start(client, owner, customer)
    def fail(*args): raise RuntimeError('network unavailable')
    monkeypatch.setattr(ct, 'api', fail)
    assert client.put(PATH, headers=owner, json={'enabled': False}).status_code == 200
    invoked = []
    def webhook(bot, method, body):
        invoked.append(method)
        return {'id': 456789, 'username': 'AirLinkTestBot', 'is_bot': True} if method == 'getMe' else {'url': 'https://example.invalid/hook'}
    monkeypatch.setattr(ct, 'api', webhook)
    assert client.put(PATH, headers=owner, json={'enabled': True}).status_code == 409
    assert invoked == ['getMe', 'getWebhookInfo']


def test_actual_telegram_request_has_fixed_endpoint_and_redacts_network_error(customer, monkeypatch):
    import urllib.request
    # Fixture replaces api; obtain the real helper from a fresh module loading its source.
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location('airlink.customer_telegram_transport_test', Path(ct.__file__))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    actor, _, _, _ = customer
    requests = []
    class Opener:
        def open(self, request, timeout):
            requests.append(request)
            raise OSError('PRIVATE secret URL ' + request.full_url)
    monkeypatch.setattr(urllib.request, 'build_opener', lambda *a: Opener())
    with SessionLocal() as db:
        with pytest.raises(RuntimeError) as error:
            module.api(db.get(ct.Bot, actor), 'sendMessage', {'chat_id': '789', 'text': 'fixture'})
        assert str(error.value) == ct.FAILURE
    assert requests[0].full_url == 'https://api.telegram.org/bot' + TOKEN + '/sendMessage'


@pytest.mark.parametrize('method', ['card', 'credit', 'extend', 'fib', 'fastpay'])
def test_manager_activation_uses_existing_owner_link_and_owner_token(client, owner, customer, monkeypatch, method):
    from airlink.models import RechargePayment
    actor, record, calls, _ = customer
    start(client, owner, customer)
    mid, manager = user(client, owner, 'manager', 'shared-bot-manager')
    if method == 'fib':
        assert client.put('/api/users/' + mid + '/sections', headers=owner, json={
            'sections': ['isp_card', 'fib_recharge'],
            'editable_sections': ['isp_card', 'fib_recharge'], 'deletable_sections': []}).status_code == 200
    assert client.put('/api/integrations/sas4', headers=manager, json=SETTINGS).status_code == 200
    status = client.get(PATH + '/users/7', headers=manager)
    assert status.status_code == 200 and status.json()['linked']
    assert client.post(PATH + '/users/7/link', headers=manager, json={}).status_code == 409
    activations = []
    def activate(connection, password, customer_id, data):
        assert connection.user_id == mid and customer_id == 7
        activations.append(data.transaction_id)
        return {'recharged': True}
    monkeypatch.setattr(sas4, 'redeem_card', activate)
    transaction = 'e' * 32
    if method in ('fib', 'fastpay'):
        with SessionLocal() as db:
            db.add(RechargePayment(id=transaction, user_id=mid, sas4_user_id=7, sas4_username=SETTINGS['username'],
                provider=method, environment='production', encrypted_credentials='fixture', status='pending',
                amount='2500', currency='IQD', quote={'manager_cost': '2000', 'profile_id': 3, 'expiration': record['expiration']}))
            db.commit()
        monkeypatch.setattr(payments, 'verify_provider_payment', lambda row: 'paid')
        payments.process_pending()
        payments.process_pending()
    else:
        body = {'method': method, 'pin': 'PRIVATE-PIN', 'transaction_id': transaction,
                'expected_cost': '2000', 'expected_profile_id': 3, 'extension_id': 1}
        for _ in range(2):
            response = client.post('/api/integrations/sas4/users/7/recharge', headers=manager, json=body)
            assert response.status_code == 200, response.text
    assert activations == [transaction]
    original_api = ct.api
    senders = []
    def api(bot, operation, body):
        if operation == 'sendMessage':
            senders.append(bot.user_id)
            assert cipher().decrypt(bot.encrypted_token.encode()).decode() == TOKEN
        return original_api(bot, operation, body)
    monkeypatch.setattr(ct, 'api', api)
    with SessionLocal() as db:
        events = db.scalars(select(ct.Event).where(ct.Event.kind == method)).all()
        assert len(events) == 1 and events[0].user_id == actor
        assert db.get(ct.Bot, mid) is None and db.get(ct.Link, (mid, 7)) is None
        ct.deliver(db, events[0])
        assert events[0].status == 'sent'
    assert senders == [actor]


def test_manager_creates_shared_link_but_must_have_matching_sas4_access(client, owner, customer, monkeypatch):
    actor, record, _, updates = customer
    mid, manager = user(client, owner, 'manager', 'customer-link-manager')
    client.put('/api/integrations/sas4', headers=manager, json=SETTINGS)
    checked = []
    def lookup(db, viewer, cid):
        checked.append(viewer.id)
        return record if viewer.id == actor else {**record, 'username': 'different-customer'}
    monkeypatch.setattr(ct, 'record_for', lookup)
    assert client.post(PATH + '/users/7/link', headers=manager, json={}).status_code == 409
    assert set(checked) == {actor, mid}
    monkeypatch.setattr(ct, 'record_for', lambda *args: dict(record))
    token = start(client, manager, (actor, record, [], updates))
    assert token
    assert client.get(PATH + '/users/7', headers=owner).json()['linked']
    assert client.put(PATH + '/users/7/language', headers=manager, json={'language': 'ar'}).status_code == 200
    assert client.get(PATH + '/users/7', headers=owner).json()['language'] == 'ar'
    def denied(*args): raise ct.HTTPException(502, 'No SAS4 access')
    monkeypatch.setattr(ct, 'record_for', denied)
    assert client.get(PATH + '/users/7', headers=manager).status_code == 502
    assert client.delete(PATH + '/users/7', headers=manager).status_code == 502
    monkeypatch.setattr(ct, 'record_for', lambda *args: dict(record))
    assert client.delete(PATH + '/users/7', headers=manager).status_code == 200
    assert not client.get(PATH + '/users/7', headers=owner).json()['linked']


def test_legacy_manager_bot_is_never_polled_or_used_for_delivery(client, owner, customer, monkeypatch):
    actor, record, _, _ = customer
    mid, manager = user(client, owner, 'manager', 'legacy-bot-manager')
    client.put('/api/integrations/sas4', headers=manager, json=SETTINGS)
    senders = []
    original = ct.api
    def api(bot, operation, body):
        senders.append(bot.user_id)
        return original(bot, operation, body)
    monkeypatch.setattr(ct, 'api', api)
    with SessionLocal() as db:
        db.add(ct.Bot(user_id=mid, bot_id='987', username='LegacyManagerBot', encrypted_token=cipher().encrypt(b'987:legacy').decode(),
            sas4_username=SETTINGS['username'], enabled=True))
        db.flush()
        db.add(ct.Link(user_id=mid, customer_id=7, customer_username='customer', chat_id='999', version='legacy'))
        db.add(ct.Event(id='legacy-event', user_id=mid, customer_id=7, version='legacy', kind='card'))
        db.commit()
    ct.tick()
    assert senders == [actor]
    with SessionLocal() as db:
        assert db.get(ct.Event, 'legacy-event').status == 'cancelled'
        db.get(User, actor).active = False
        db.commit()
        assert ct.configured(db, mid) is None


@pytest.mark.parametrize('owner_count', [0, 1, 2])
def test_sender_migration_preserves_unambiguous_owner_only(tmp_path, owner_count):
    import importlib.util
    from pathlib import Path
    from sqlalchemy import create_engine, text, inspect
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    def migration(name, connection):
        spec = importlib.util.spec_from_file_location(name, Path(ct.__file__).resolve().parents[2] / 'database/versions' / name)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.op = Operations(MigrationContext.configure(connection))
        return module
    engine = create_engine('sqlite:///' + str(tmp_path / 'shared-sender.sqlite'))
    with engine.begin() as connection:
        connection.execute(text('CREATE TABLE users (id VARCHAR(36) PRIMARY KEY, role VARCHAR(16), active BOOLEAN)'))
        migration('b38cf705196f_customer_telegram.py', connection).upgrade()
        for i in range(owner_count + 1):
            key = str(i)
            connection.execute(text('INSERT INTO users VALUES (:id, :role, true)'), {'id': key, 'role': 'manager' if i == 0 else 'owner'})
            connection.execute(ct.Bot.__table__.insert().values(user_id=key, bot_id=key, username='Bot'+key,
                encrypted_token='fixture', sas4_username='fixture', enabled=True))
            connection.execute(ct.Event.__table__.insert().values(id=key, user_id=key, customer_id=7, version='legacy', kind='card'))
        shared = migration('c49da816207b_owner_customer_telegram.py', connection)
        shared.upgrade()
        selected = connection.execute(text('SELECT user_id FROM customer_telegram_sender')).scalars().all()
        assert selected == (['1'] if owner_count == 1 else [])
        states = dict(connection.execute(text('SELECT user_id, status FROM customer_telegram_events')).all())
        assert states['0'] == 'cancelled'
        if owner_count == 1: assert states['1'] == 'pending'
        shared.downgrade()
        assert 'customer_telegram_sender' not in inspect(connection).get_table_names()
        assert connection.execute(text('SELECT count(*) FROM customer_telegram_bots')).scalar_one() == owner_count + 1


@pytest.mark.parametrize('language', ['en', 'ar', 'ku'])
@pytest.mark.parametrize('as_manager', [False, True])
def test_customer_test_sends_once_from_owner_in_saved_language(client, owner, customer, monkeypatch, language, as_manager):
    actor, _, calls, _ = customer
    start(client, owner, customer, language)
    headers = owner
    if as_manager:
        _, headers = user(client, owner, 'manager', 'telegram-test-manager')
    original = ct.api
    def api(bot, method, body):
        if method == 'sendMessage': assert bot.user_id == actor
        return original(bot, method, body)
    monkeypatch.setattr(ct, 'api', api)
    result = client.post(PATH + '/users/7/test', headers=headers)
    assert result.status_code == 200 and result.json()['sent'] is True
    assert client.post(PATH + '/users/7/test', headers=headers).status_code == 429
    sent = [body for method, body in calls if method == 'sendMessage']
    assert len(sent) == 1 and sent[0]['chat_id'] == '789'
    assert ct.LABELS[language]['test'] in sent[0]['text']
    assert 'PRIVATE' not in str(sent) + result.text
    with SessionLocal() as db:
        event = db.scalar(select(ct.Event).where(ct.Event.kind == 'test'))
        assert event.status == 'sent' and event.attempts == 1
        assert db.get(ct.Link, (actor, 7)).last_sent_at is not None


def test_customer_test_requires_link_enabled_owner_and_edit_access(client, owner, customer, monkeypatch):
    actor, _, calls, _ = customer
    assert client.post(PATH + '/users/7/test', headers=owner).status_code == 409
    start(client, owner, customer)
    mid, manager = user(client, owner, 'manager', 'readonly-test-manager')
    with SessionLocal() as db:
        db.add(UserSectionEdits(user_id=mid, sections=[])); db.commit()
    assert client.post(PATH + '/users/7/test', headers=manager).status_code == 403
    with SessionLocal() as db:
        db.get(ct.Bot, actor).enabled = False; db.commit()
    assert client.post(PATH + '/users/7/test', headers=owner).status_code == 409
    assert not [call for call in calls if call[0] == 'sendMessage']


def test_failed_customer_test_is_recorded_without_automatic_retry(client, owner, customer, monkeypatch):
    actor, _, _, _ = customer
    start(client, owner, customer)
    attempts = []
    def fail(*args):
        attempts.append(True)
        raise RuntimeError('PRIVATE-TOKEN network failure')
    monkeypatch.setattr(ct, 'api', fail)
    response = client.post(PATH + '/users/7/test', headers=owner)
    assert response.status_code == 502 and 'PRIVATE' not in response.text
    with SessionLocal() as db:
        event = db.scalar(select(ct.Event).where(ct.Event.kind == 'test'))
        assert event.status == 'failed' and event.attempts == 1
        assert db.get(ct.Link, (actor, 7)).last_error == ct.FAILURE
        assert db.get(ct.Link, (actor, 7)).last_sent_at is None
    assert client.post(PATH + '/users/7/test', headers=owner).status_code == 429
    assert len(attempts) == 1


def test_customer_test_rechecks_owner_customer_identity(client, owner, customer, monkeypatch):
    actor, record, calls, _ = customer
    start(client, owner, customer)
    mid, manager = user(client, owner, 'manager', 'mismatch-test-manager')
    monkeypatch.setattr(ct, 'record_for', lambda db, viewer, cid:
        {**record, 'username': 'changed-owner-customer'} if viewer.id == actor else record)
    assert client.post(PATH + '/users/7/test', headers=manager).status_code == 409
    assert not [call for call in calls if call[0] == 'sendMessage']


@pytest.mark.parametrize('phone', ['+9647501234567', '009647501234567', '07501234567', '7501234567', '+٩٦٤٧٥٠١٢٣٤٥٦٧'])
def test_phone_normalization_matches_international_and_iraqi_notation(phone):
    assert ct.normalized_phone(phone) == '9647501234567'


@pytest.mark.parametrize('phone', [None, True, '', '123', 'unknown', '+9647501234567ext2', '0000', '++9647501234567'])
def test_invalid_phone_is_not_treated_as_telegram_account(phone):
    assert ct.normalized_phone(phone) is None


@pytest.mark.parametrize('case', ['correct', 'wrong_phone', 'someone_else', 'missing_user_id', 'changed_sas4', 'expired', 'text_only'])
def test_phone_share_must_match_sender_and_current_isp_record(client, owner, customer, case):
    actor, record, calls, updates = customer
    result = client.post(PATH + '/users/7/link', headers=owner, json={})
    assert result.status_code == 200
    token = parse_qs(urlparse(result.json()['url']).query)['start'][0]
    updates[:] = [{'update_id': 1, 'message': {'text': '/start ' + token,
        'chat': {'id': 789, 'type': 'private'}, 'from': {'id': 789, 'is_bot': False}}}]
    with SessionLocal() as db:
        ct.poll_bot(db, db.get(ct.Bot, actor))
        link = db.get(ct.Link, (actor, 7))
        assert link.chat_id is None and link.pending_chat_id == '789'
        assert link.phone_hash == ct.phone_hash(record) and record['phone'] not in link.phone_hash
        assert link.phone_verified_at is None and db.scalar(select(ct.Event)) is None
        if case == 'expired':
            link.token_expires = now() - timedelta(seconds=1); db.commit()
    status = client.get(PATH + '/users/7', headers=owner).json()
    assert not status['linked'] and not status['phone_verified']
    assert status['awaiting_phone'] is (case != 'expired')
    assert client.post(PATH + '/users/7/test', headers=owner).status_code == 409
    prompts = [body for method, body in calls if method == 'sendMessage']
    assert len(prompts) == 1 and prompts[0]['reply_markup']['keyboard'][0][0]['request_contact'] is True
    assert record['phone'] not in str(prompts)
    contact = {'phone_number': '07501234567', 'user_id': 789}
    if case == 'wrong_phone': contact['phone_number'] = '+9647509999999'
    if case == 'someone_else': contact['user_id'] = 999
    if case == 'missing_user_id': del contact['user_id']
    if case == 'changed_sas4': record['phone'] = '+9647509999999'
    message = {'chat': {'id': 789, 'type': 'private'}, 'from': {'id': 789, 'is_bot': False}, 'contact': contact}
    if case == 'text_only':
        del message['contact']; message['text'] = '07501234567'
    updates[:] = [{'update_id': 2, 'message': message}]
    with SessionLocal() as db:
        ct.poll_bot(db, db.get(ct.Bot, actor))
        link = db.get(ct.Link, (actor, 7))
        assert bool(link.phone_verified_at) is (case == 'correct')
        assert bool(link.chat_id) is (case == 'correct')
        if case == 'correct':
            event = db.scalar(select(ct.Event))
            ct.deliver(db, event)
            assert event.status == 'sent'
            assert calls[-1][1]['reply_markup'] == {'remove_keyboard': True}
        else:
            assert db.scalar(select(ct.Event)) is None


def test_phone_change_blocks_all_messages_and_allows_reverification(client, owner, customer):
    actor, record, calls, _ = customer
    start(client, owner, customer)
    record['phone'] = '+9647509999999'
    assert not client.get(PATH + '/users/7', headers=owner).json()['linked']
    assert client.post(PATH + '/users/7/test', headers=owner).status_code == 409
    with SessionLocal() as db:
        event = db.scalar(select(ct.Event))
        ct.deliver(db, event)
        assert event.status == 'cancelled'
        assert 'phone' in db.get(ct.Link, (actor, 7)).last_error
    assert not [call for call in calls if call[0] == 'sendMessage']
    assert client.post(PATH + '/users/7/link', headers=owner, json={}).status_code == 200


def test_phone_migration_does_not_mark_existing_links_verified(tmp_path):
    import importlib.util
    from pathlib import Path
    from sqlalchemy import create_engine, text, inspect
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    spec = importlib.util.spec_from_file_location('phone_migration', Path(ct.__file__).resolve().parents[2] /
        'database/versions/d50eb927318c_customer_telegram_phone.py')
    migration = importlib.util.module_from_spec(spec); spec.loader.exec_module(migration)
    engine = create_engine('sqlite:///' + str(tmp_path / 'phone-migration.sqlite'))
    with engine.begin() as connection:
        connection.execute(text('CREATE TABLE customer_telegram_links (customer_id INTEGER PRIMARY KEY, chat_id VARCHAR(30), token_hash VARCHAR(64))'))
        connection.execute(text("INSERT INTO customer_telegram_links VALUES (7, '789', 'invitation')"))
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        row = connection.execute(text('SELECT chat_id, token_hash, phone_hash, phone_verified_at FROM customer_telegram_links')).one()
        assert tuple(row) == ('789', 'invitation', None, None)
        migration.downgrade()
        assert {c['name'] for c in inspect(connection).get_columns('customer_telegram_links')} == {'customer_id', 'chat_id', 'token_hash'}


def test_phone_required_for_automatic_notifications_but_existing_chat_can_test(client, owner, customer):
    actor, record, calls, _ = customer
    record['phone'] = ''
    assert client.post(PATH + '/users/7/link', headers=owner, json={}).status_code == 409
    assert client.get(PATH + '/users/7', headers=owner).json()['phone_available'] is False
    with SessionLocal() as db:
        db.add(ct.Link(user_id=actor, customer_id=7, customer_username='customer', chat_id='789'))
        db.commit()
        ct.enqueue(db, actor, 7, 'card', 'legacy-unverified')
        db.commit()
        assert db.scalar(select(ct.Event)) is None
    record['phone'] = '+9647501234567'
    status = client.get(PATH + '/users/7', headers=owner).json()
    assert not status['linked'] and status['telegram_linked'] and status['test_ready']
    assert client.post(PATH + '/users/7/test', headers=owner).json()['sent'] is True
    sent = [call for call in calls if call[0] == 'sendMessage']
    assert len(sent) == 1 and sent[0][1]['chat_id'] == '789'
    with SessionLocal() as db:
        assert db.get(ct.Link, (actor, 7)).phone_verified_at is None
    assert client.post(PATH + '/users/7/link', headers=owner, json={}).status_code == 200


def test_owner_account_language_overrides_older_customer_bot_language(client, owner, customer):
    from airlink.models import RechargeTelegramSettings
    actor, _, calls, _ = customer
    start(client, owner, customer, 'en')
    with SessionLocal() as db:
        db.add(RechargeTelegramSettings(id=1, user_id=actor, enabled=False, sender_id='789',
            sas4_username=SETTINGS['username'], language='ar', timezone='Asia/Baghdad'))
        db.commit()
    result = client.get(PATH + '/users/7', headers=owner).json()
    assert result['language'] == 'ar' and result['language_managed']
    assert client.put(PATH + '/users/7/language', headers=owner, json={'language': 'en'}).status_code == 409
    assert client.post(PATH + '/users/7/test', headers=owner).status_code == 200
    messages = [body['text'] for method, body in calls if method == 'sendMessage']
    assert ct.LABELS['ar']['test'] in messages[-1]
