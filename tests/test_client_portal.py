"""Client sessions cannot become staff sessions, choose subscribers, or trust browser IP hints."""
import ipaddress
from contextlib import contextmanager
from datetime import timedelta
from types import SimpleNamespace
import httpx
import pytest
from airlink import client_portal as portal, sas4, payments
from airlink.db import SessionLocal
from airlink.models import ClientPortalSession, RechargePayment, now
from test_sas4 import SETTINGS
from test_payments import QUOTE, encrypted
from test_api import user

HEADERS = {'X-AirLink-Request': '1'}


@pytest.fixture
def configured(client, owner, monkeypatch):
    client.put('/api/integrations/sas4', headers=owner, json=SETTINGS)
    result = client.put('/api/client-portal', headers=owner, json={'enabled': True, 'subscriber_networks': ['10.0.0.0/8']})
    assert result.status_code == 200, result.text
    state = {'id': 7, 'username': 'subscriber', 'permissions': ['prm_ucp_activate'], 'valid': True, 'enabled': True}
    def ucp(remote, route, token=None, body=None):
        if route == 'resources/config': return {'status': 200, 'data': {'requires_captcha': 0}}
        if route == 'auth/login':
            assert body['username'] == 'subscriber'
            assert body['password'] == 'PPPOE-PASSWORD'
            if not state['valid']: raise sas4.SAS4Error('PRIVATE-BODY')
            return {'status': 200, 'token': 'PRIVATE-NATIVE-TOKEN'}
        assert route == 'user' and token == 'PRIVATE-NATIVE-TOKEN'
        return {'status': 200, 'data': {'id': state['id'], 'username': state['username']}, 'permissions': state['permissions']}
    monkeypatch.setattr(portal, 'ucp', ucp)
    def validate(db, actor, customer_id, username):
        assert customer_id == 7 and username == 'subscriber'
        if not state['enabled']: raise portal.HTTPException(401, 'Account unavailable')
        return {'id': 7, 'username': 'subscriber', 'enabled': 1,
                'firstname': 'Ava', 'lastname': 'Sample', 'phone': '07500000000', 'password': 'PRIVATE'}
    monkeypatch.setattr(portal, 'validate_customer', validate)
    monkeypatch.setattr(sas4, 'fetch_recharge', lambda *a, **k: {**QUOTE, 'methods': {'card': True}, 'transaction_id': 'a'*32})
    return state


def login(client):
    options = client.get('/api/client/login-options').json()
    response = client.post('/api/client/login', headers=HEADERS, json={'username': 'subscriber', 'password': 'PPPOE-PASSWORD', 'challenge_id': options['challenge_id']})
    assert response.status_code == 200, response.text
    return response, options


def test_separate_session_cookie_no_staff_access_and_no_credentials_returned(client, owner, configured):
    response, _ = login(client)
    assert 'httponly' in response.headers['set-cookie'].lower()
    assert 'Path=/api/client' in response.headers['set-cookie']
    assert 'samesite=strict' in response.headers['set-cookie'].lower()
    assert 'TOKEN' not in response.text and 'PASSWORD' not in response.text
    assert client.get('/api/auth/me').status_code == 401
    assert client.get('/api/users').status_code == 401
    response = client.get('/api/client/account')
    assert response.status_code == 200 and response.json()['username'] == 'subscriber'
    assert response.json()['first_name'] == 'Ava'
    assert response.json()['last_name'] == 'Sample'
    assert response.json()['phone'] == '07500000000'
    assert response.json()['recharge_cost'] == QUOTE['customer_price']
    assert response.json()['currency'] == QUOTE['currency']
    assert 'PRIVATE' not in response.text
    assert 'manager_balance' not in response.text and 'manager_cost' not in response.text
    with SessionLocal() as db:
        session = db.query(ClientPortalSession).one()
        assert 'PRIVATE-NATIVE-TOKEN' not in session.encrypted_token
        assert session.digest != client.cookies.get(portal.COOKIE)


def test_wrong_password_replay_and_sensitive_validation(client, owner, configured):
    configured['valid'] = False
    options = client.get('/api/client/login-options').json()
    body = {'username': 'subscriber', 'password': 'PPPOE-PASSWORD', 'challenge_id': options['challenge_id']}
    response = client.post('/api/client/login', headers=HEADERS, json=body)
    assert response.status_code == 401 and 'PRIVATE' not in response.text
    assert client.get('/api/client/account').status_code == 401
    configured['valid'] = True
    assert client.post('/api/client/login', headers=HEADERS, json=body).status_code == 401
    response = client.post('/api/client/login', headers=HEADERS, json={**body, 'unexpected': 'PRIVATE-PASSWORD'})
    assert response.status_code == 422 and 'PRIVATE' not in response.text


def test_csrf_and_staff_token_do_not_authenticate_customer(client, owner, configured):
    assert client.get('/api/client/account', headers=owner).status_code == 401
    options = client.get('/api/client/login-options').json()
    body = {'username': 'subscriber', 'password': 'PPPOE-PASSWORD', 'challenge_id': options['challenge_id']}
    assert client.post('/api/client/login', json=body).status_code == 403
    assert client.post('/api/client/login', headers={**HEADERS, 'Origin': 'https://evil.example'}, json=body).status_code == 403
    assert client.post('/api/client/auto-login', headers={'X-Forwarded-For': '10.1.2.3'}).status_code == 403


def test_owner_config_and_logout_revoke_client_sessions(client, owner, configured):
    login(client)
    assert client.post('/api/client/logout', headers=HEADERS).status_code == 200
    assert client.get('/api/client/account').status_code == 401
    login(client)
    client.put('/api/client-portal', headers=owner, json={'enabled': True, 'subscriber_networks': []})
    assert client.get('/api/client/account').status_code == 401
    _, manager = user(client, owner, 'manager', 'portal-manager')
    assert client.put('/api/client-portal', headers=manager, json={'enabled': True}).status_code == 403
    assert client.put('/api/client-portal', headers=owner, json={'enabled': True, 'subscriber_networks': ['0.0.0.0/0']}).status_code == 422


def test_customer_id_and_provider_cannot_be_supplied_and_only_own_payment_visible(client, owner, configured, monkeypatch):
    login(client)
    body = {'transaction_id': 'a'*32, 'expected_amount': '25000', 'expected_profile_id': 3,
            'expected_expiration': QUOTE['expiration'], 'radius_card_id': 42, 'radius_series': 'SERIES-1'}
    for extra in [{'user_id': 8}, {'provider': 'fastpay'}, {'card_source': 'saved_pin'}]:
        assert client.post('/api/client/payments', headers=HEADERS, json={**body, **extra}).status_code == 422
    seen = []
    def begin(customer_id, data, actor, db):
        seen.append((customer_id, data.provider, data.card_source, actor.role))
        return {'id': data.transaction_id, 'status': 'pending'}
    monkeypatch.setattr(payments, 'begin_payment', begin)
    assert client.post('/api/client/payments', headers=HEADERS, json=body).status_code == 200
    assert seen == [(7, 'fib', 'radius_pin', 'owner')]
    staff_id, _ = user(client, owner, 'manager', 'customer-payment-staff')
    with SessionLocal() as db:
        session = db.query(ClientPortalSession).one()
        for index, customer_id in enumerate([7, 8]):
            db.add(RechargePayment(id=str(index)*32, user_id=session.owner_id, sas4_user_id=customer_id,
                sas4_username=SETTINGS['username'], provider='fib', environment='sandbox', encrypted_credentials=encrypted(),
                status='pending', amount='25000', currency='IQD', quote={}))
        db.add(RechargePayment(id='2'*32, user_id=staff_id, sas4_user_id=7,
            sas4_username='staff-radius', provider='fib', environment='sandbox', encrypted_credentials=encrypted(),
            status='pending', amount='25000', currency='IQD', quote={'merchant_owner_id': session.owner_id}))
        db.commit()
    assert client.get('/api/client/payments/'+'0'*32).status_code == 200
    assert client.get('/api/client/payments/'+'1'*32).status_code == 404
    assert client.get('/api/client/payments/'+'2'*32).status_code == 404
    assert len(client.get('/api/client/payments').json()) == 1


def test_manual_recharge_is_card_only_and_bound_to_session(client, owner, configured, monkeypatch):
    login(client)
    seen = []
    monkeypatch.setattr(sas4, 'recharge_user_card', lambda user_id, data, actor, db: seen.append((user_id,data.method,data.pin)) or {'recharged': True})
    body = {'pin': 'MY-PIN', 'transaction_id': 'a'*32, 'expected_profile_id': 3, 'expected_expiration': QUOTE['expiration']}
    assert client.post('/api/client/recharge', headers=HEADERS, json={**body, 'user_id': 8}).status_code == 422
    assert client.post('/api/client/recharge', headers=HEADERS, json=body).status_code == 200
    assert seen == [(7, 'card', 'MY-PIN')]
    configured['permissions'] = []
    assert client.post('/api/client/recharge', headers=HEADERS, json=body).status_code == 403
    assert client.get('/api/client/fib-quote').status_code == 403
    configured['enabled'] = False
    assert client.get('/api/client/account').status_code == 401


def test_auto_login_ignores_untrusted_headers_and_binds_network_session(client, owner, configured, monkeypatch):
    monkeypatch.setattr(portal, 'automatic_identity', lambda *a, **k: pytest.fail('Not a trusted subscriber IP'))
    assert client.post('/api/client/auto-login', headers={**HEADERS, 'X-Forwarded-For':'10.1.2.3', 'X-Real-IP':'10.1.2.3'}).json()['authenticated'] is False
    monkeypatch.setattr(portal, 'peer_ip', lambda request: ipaddress.ip_address('10.1.2.3'))
    monkeypatch.setattr(portal, 'automatic_identity', lambda *a, **k: (7,'subscriber'))
    assert client.post('/api/client/auto-login', headers=HEADERS).json()['authenticated']
    assert client.get('/api/client/account').status_code == 200
    monkeypatch.setattr(portal, 'peer_ip', lambda request: ipaddress.ip_address('10.1.2.4'))
    assert client.get('/api/client/account').status_code == 401


@pytest.mark.parametrize('kind', ['fresh','stale','duplicate','wrong_ip','missing_accounting'])
def test_auto_login_requires_unique_fresh_accounting(client, owner, configured, monkeypatch, kind):
    from airlink.models import User
    started = now() - timedelta(seconds=60 if kind != 'stale' else 900)
    row = {'framedipaddress': '10.1.2.3', 'username':'subscriber','user_details': {'id':7},
           'acctstarttime': started.isoformat(), 'acctsessiontime': 0}
    if kind == 'wrong_ip': row['framedipaddress'] = '10.1.2.4'
    if kind == 'missing_accounting': row.pop('acctsessiontime')
    rows = [row, row] if kind == 'duplicate' else [row]
    @contextmanager
    def session(*args):
        with httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={'data':rows,'total':len(rows),'per_page':100}))) as remote:
            yield remote, {}
    monkeypatch.setattr(sas4, 'sas4_session', session)
    with SessionLocal() as db:
        actor = db.query(User).filter(User.role=='owner').one()
        assert portal.automatic_identity(db, actor, ipaddress.ip_address('10.1.2.3')) == ((7,'subscriber') if kind == 'fresh' else None)


def test_invalid_encrypted_customer_token_requires_sign_in(client, owner, configured):
    login(client)
    with SessionLocal() as db:
        session = db.query(ClientPortalSession).one()
        session.encrypted_token = 'not-a-valid-token'
        db.commit()
    assert client.get('/api/client/account').status_code == 401


def test_native_auth_uses_customer_api_and_encrypted_payload():
    def handle(request):
        assert request.url.path == '/user/api/index.php/api/auth/login'
        assert b'PRIVATE-PASSWORD' not in request.content
        assert 'authorization' not in request.headers
        return httpx.Response(200, json={'status': 200, 'token': 'native-token'})
    with httpx.Client(transport=httpx.MockTransport(handle)) as remote:
        assert portal.ucp(remote, 'auth/login', body={'username':'subscriber', 'password':'PRIVATE-PASSWORD'})['token'] == 'native-token'


def test_portal_migration_preserves_local_users(client, owner):
    import importlib.util
    from pathlib import Path
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import inspect, select
    from airlink.db import engine
    from airlink.models import User
    with SessionLocal() as db:
        before = list(db.scalars(select(User.id)))
    path = Path(__file__).resolve().parents[1] / 'database/versions/b08de7149f25_client_portal.py'
    spec = importlib.util.spec_from_file_location('portal_migration', path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with engine.begin() as connection:
        migration.op = Operations(MigrationContext.configure(connection))
        migration.downgrade()
        assert 'client_portal_sessions' not in inspect(connection).get_table_names()
        migration.upgrade()
        assert 'client_portal_sessions' in inspect(connection).get_table_names()
    with SessionLocal() as db:
        assert list(db.scalars(select(User.id))) == before


@pytest.mark.parametrize('mode', ['fresh', 'stale_signal', 'old_signal', 'stale_sessions', 'offline', 'ambiguous', 'shared_ip'])
def test_connection_only_exposes_fresh_own_signal(client, owner, configured, monkeypatch, mode):
    from airlink.online_sessions import service as sessions
    from airlink.customer_probes import service as probes
    login(client)
    mine = {'id': 7, 'username': 'subscriber', 'ip_address': '10.1.2.3', 'session_id': 123}
    other = {'id': 8, 'username': 'someone-else', 'ip_address': '10.1.2.4', 'session_id': 456}
    rows = [mine, other]
    if mode == 'offline': rows = [other]
    if mode == 'ambiguous': rows.append(dict(mine))
    if mode == 'shared_ip': other['ip_address'] = mine['ip_address']
    monkeypatch.setattr(sessions, 'snapshot', lambda *a: {'collection_status': 'stale' if mode == 'stale_sessions' else 'available', 'clients': rows})
    def enrich(db, actor, result):
        assert result['clients'] == [mine]
        assert mode not in ('offline', 'ambiguous', 'shared_ip', 'stale_sessions')
        mine.update(signal_dbm=-62, api_password='PRIVATE', ssid='PRIVATE',
            telemetry_status='available', telemetry_collected_at=(now()-timedelta(seconds=120 if mode=='old_signal' else 5)).isoformat(),
            telemetry_stale_fields=['signal_dbm'] if mode == 'stale_signal' else [])
    monkeypatch.setattr(probes, 'enrich', enrich)
    response = client.get('/api/client/connection?user_id=8&address=10.1.2.4')
    assert response.status_code == 200
    assert response.json()['signal_dbm'] == (-62 if mode == 'fresh' else None)
    assert all(value not in response.text for value in ['PRIVATE', 'someone-else', '10.1.2.3', '10.1.2.4'])
    client.post('/api/client/logout', headers=HEADERS)
    assert client.get('/api/client/connection').status_code == 401


def test_cards_catalog_requires_client_session_and_uses_saved_owner(client, owner, configured, monkeypatch):
    from airlink import client_catalog
    assert client.get('/api/client/cards',headers=owner).status_code==401
    login(client)
    seen=[]
    def fetch(connection,password):
        seen.append((connection.username,password))
        return {'items':[{'profile_id':97,'name':'AirLink Basic','price_iqd':'14000'}], 'currency':'IQD'}
    monkeypatch.setattr(client_catalog,'fetch_catalog',fetch)
    response=client.get('/api/client/cards?user_id=8')
    assert response.status_code==200
    assert seen==[(SETTINGS['username'],SETTINGS['password'])]
    assert 'password' not in response.text


def test_owner_can_add_subscriber_ranges_and_auto_login_uses_saved_list(client, owner, configured, monkeypatch):
    address = ipaddress.ip_address('172.20.5.10')
    matches = []
    monkeypatch.setattr(portal, 'peer_ip', lambda request: address)
    monkeypatch.setattr(portal, 'automatic_identity', lambda db, actor, ip, **kwargs: matches.append(str(ip)) or (7, 'subscriber'))
    assert client.post('/api/client/auto-login', headers=HEADERS).json()['authenticated'] is False
    assert matches == []
    result = client.put('/api/client-portal', headers=owner, json={
        'enabled': True, 'subscriber_networks': ['10.0.0.0/8', '172.0.0.0/8', '172.0.0.0/8']})
    assert result.status_code == 200, result.text
    assert client.get('/api/client-portal', headers=owner).json()['subscriber_networks'] == ['10.0.0.0/8', '172.0.0.0/8']
    assert client.post('/api/client/auto-login', headers=HEADERS).json()['authenticated'] is True
    assert matches == ['172.20.5.10']
    assert client.put('/api/client-portal', headers=owner, json={'enabled': True, 'subscriber_networks': []}).status_code == 200
    assert client.post('/api/client/auto-login', headers=HEADERS).json()['authenticated'] is False
    assert matches == ['172.20.5.10']


def test_auto_login_explains_range_mismatch_without_trusting_headers_or_disclosing_accounts(client, owner, configured, monkeypatch):
    monkeypatch.setattr(portal, 'peer_ip', lambda request: ipaddress.ip_address('172.20.5.10'))
    monkeypatch.setattr(portal, 'automatic_identity', lambda *a, **k: pytest.fail('Outside saved subscriber range'))
    response = client.post('/api/client/auto-login', headers={**HEADERS, 'X-Forwarded-For': '10.1.2.3'})
    assert response.json() == {'authenticated': False, 'reason': 'outside_subscriber_ranges', 'source_ip': '172.20.5.10'}
    assert 'set-cookie' not in response.headers
    assert client.get('/api/auth/me').status_code == 401


@pytest.mark.parametrize('kind,expected', [
    ('fresh_z', None), ('stopped', 'session_not_found'), ('stale', 'stale_session'),
    ('future', 'accounting_clock_mismatch'), ('duplicate', 'ambiguous_session'),
    ('overflow', 'accounting_unavailable'), ('bad_page', 'accounting_unavailable'),
    ('bad_count', 'accounting_unavailable'), ('invalid_row', 'accounting_unavailable'),
])
def test_auto_login_handles_accounting_failures_and_reports_safe_reasons(client, owner, configured, monkeypatch, kind, expected):
    from airlink.models import User
    started = now() - timedelta(seconds=60)
    row = {'framedipaddress': '10.1.2.3', 'username': 'subscriber', 'user_details': {'id': 7},
           'acctstarttime': started.isoformat().replace('+00:00', 'Z'), 'acctsessiontime': 0}
    if kind == 'stopped': row['acctstoptime'] = now().isoformat()
    if kind == 'stale': row['acctstarttime'] = (now() - timedelta(minutes=10)).isoformat()
    if kind == 'future': row['acctstarttime'] = (now() + timedelta(minutes=10)).isoformat()
    if kind == 'overflow': row['acctsessiontime'] = 10**100
    rows = [row, row] if kind == 'duplicate' else [None] if kind == 'invalid_row' else [row]
    result = {'data': rows, 'total': len(rows), 'per_page': 0 if kind == 'bad_count' else 100,
              'current_page': 2 if kind == 'bad_page' else 1}
    @contextmanager
    def session(*args):
        with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=result))) as remote:
            yield remote, {}
    monkeypatch.setattr(sas4, 'sas4_session', session)
    diagnostics = {}
    with SessionLocal() as db:
        identity = portal.automatic_identity(db, db.query(User).filter(User.role == 'owner').one(), ipaddress.ip_address('10.1.2.3'), diagnostics)
    assert identity == ((7, 'subscriber') if expected is None else None)
    assert diagnostics == ({} if expected is None else {'reason': expected})


def test_auto_login_redacts_remote_failure_and_keeps_password_login_available(client, owner, configured, monkeypatch):
    monkeypatch.setattr(portal, 'peer_ip', lambda request: ipaddress.ip_address('10.1.2.3'))
    def unavailable(*args, **kwargs):
        raise sas4.SAS4Error('PRIVATE-REMOTE-TOKEN')
    monkeypatch.setattr(portal, 'automatic_identity', unavailable)
    response = client.post('/api/client/auto-login', headers=HEADERS)
    assert response.json()['reason'] == 'verification_unavailable'
    assert response.json()['authenticated'] is False
    assert 'PRIVATE' not in response.text and 'set-cookie' not in response.headers
    response, _ = login(client)
    assert response.json()['authenticated'] is True


@pytest.mark.parametrize('address,reason,eligible,internet', [
    ('10.1.2.3', None, True, None),
    ('172.19.3.10', 'outside_subscriber_ranges', False, None),
    ('127.0.0.1', 'local_connection', False, None),
    ('8.8.8.8', 'outside_subscriber_ranges', False, '8.8.8.8'),
])
def test_connection_check_reports_only_observed_ip_without_identity_or_password(client, owner, configured, monkeypatch, address, reason, eligible, internet):
    monkeypatch.setattr(portal, 'peer_ip', lambda request: ipaddress.ip_address(address))
    monkeypatch.setattr(sas4, 'sas4_session', lambda *a, **k: pytest.fail('A connection check must not fetch customer data'))
    result = client.get('/api/client/connection-check', headers={
        'X-Forwarded-For': '10.1.2.3', 'CF-Connecting-IP': '10.1.2.3',
        'X-Real-IP': '10.1.2.3'})
    assert result.status_code == 200
    assert result.json() == {'source_ip': address, 'internet_ip': internet,
        'internet_ip_source': 'direct_connection' if internet else None,
        'auto_login_enabled': True, 'subscriber_range_match': eligible,
        'auto_login_eligible': eligible, 'reason': reason}
    assert 'set-cookie' not in result.headers
    assert client.get('/api/auth/me').status_code == 401


def test_connection_check_does_not_enable_disabled_ip_login(client, owner, configured, monkeypatch):
    assert client.put('/api/client-portal', headers=owner, json={'enabled': True, 'subscriber_networks': []}).status_code == 200
    monkeypatch.setattr(portal, 'peer_ip', lambda request: ipaddress.ip_address('10.1.2.3'))
    result = client.get('/api/client/connection-check')
    assert result.json()['auto_login_enabled'] is False
    assert result.json()['auto_login_eligible'] is False
    assert result.json()['reason'] == 'auto_login_disabled'
    assert client.post('/api/client/auto-login', headers=HEADERS).json()['authenticated'] is False


def phone_directory(monkeypatch, rows):
    @contextmanager
    def session(*args):
        with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, json={
                'data': rows, 'total': len(rows), 'per_page': 100, 'current_page': 1}))) as remote:
            yield remote, {}
    monkeypatch.setattr(sas4, 'sas4_session', session)


@pytest.mark.parametrize('phone', ['07500000000', '+9647500000000', '009647500000000', '٠٧٥٠٠٠٠٠٠٠٠', '0750 000 0000'])
def test_phone_login_uses_existing_sas4_password_and_private_native_session(client, owner, configured, monkeypatch, phone):
    phone_directory(monkeypatch, [{'id': 7, 'username': 'subscriber', 'phone': '07500000000'}])
    challenge = client.get('/api/client/login-options').json()['challenge_id']
    result = client.post('/api/client/login', headers=HEADERS, json={
        'phone': phone, 'password': 'PPPOE-PASSWORD', 'challenge_id': challenge})
    assert result.status_code == 200, result.text
    assert result.json() == {'authenticated': True}
    assert client.get('/api/client/account').json()['username'] == 'subscriber'
    assert client.get('/api/auth/me').status_code == 401
    assert 'PPPOE-PASSWORD' not in result.text and 'PRIVATE' not in result.text
    assert client.post('/api/client/login', headers=HEADERS, json={
        'phone': phone, 'password': 'PPPOE-PASSWORD', 'challenge_id': challenge}).status_code == 401


@pytest.mark.parametrize('kind', ['unknown', 'duplicate', 'wrong_password', 'wrong_identity', 'phone_changed'])
def test_phone_login_rejects_unverified_or_ambiguous_accounts(client, owner, configured, monkeypatch, kind):
    rows = [{'id': 7, 'username': 'subscriber', 'phone': '07500000000'}]
    if kind == 'unknown': rows = []
    if kind == 'duplicate': rows.append({'id': 8, 'username': 'other', 'phone': '+9647500000000'})
    if kind == 'wrong_password': configured['valid'] = False
    if kind == 'wrong_identity': configured['id'] = 8
    if kind == 'phone_changed':
        monkeypatch.setattr(portal, 'validate_customer', lambda *a: {'username': 'subscriber', 'phone': '07500000001'})
    phone_directory(monkeypatch, rows)
    challenge = client.get('/api/client/login-options').json()['challenge_id']
    result = client.post('/api/client/login', headers=HEADERS, json={
        'phone': '07500000000', 'password': 'PPPOE-PASSWORD', 'challenge_id': challenge})
    assert result.status_code == 401, result.text
    assert result.json()['detail'] == 'Invalid phone number, username, password or verification code.'
    assert 'set-cookie' not in result.headers
    assert 'PRIVATE' not in result.text and 'subscriber' not in result.text
    assert client.get('/api/client/account').status_code == 401


def test_shared_123_is_not_an_authentication_bypass(client, owner, configured, monkeypatch):
    phone_directory(monkeypatch, [{'id': 7, 'username': 'subscriber', 'phone': '07500000000'}])
    original = portal.ucp
    def ucp(remote, route, token=None, body=None):
        if route == 'auth/login':
            assert body['password'] == '123'
            raise sas4.SAS4Error('Password rejected')
        return original(remote, route, token, body)
    monkeypatch.setattr(portal, 'ucp', ucp)
    challenge = client.get('/api/client/login-options').json()['challenge_id']
    result = client.post('/api/client/login', headers=HEADERS, json={
        'phone': '07500000000', 'password': '123', 'challenge_id': challenge})
    assert result.status_code == 401 and 'set-cookie' not in result.headers


@pytest.mark.parametrize('identifier', [{}, {'phone': 'bad'}, {'phone': '07500000000', 'username': 'subscriber'}])
def test_phone_login_requires_exactly_one_valid_identifier(client, owner, configured, identifier):
    challenge = client.get('/api/client/login-options').json()['challenge_id']
    result = client.post('/api/client/login', headers=HEADERS, json={
        **identifier, 'password': 'DO-NOT-ECHO', 'challenge_id': challenge})
    assert result.status_code == 422 and 'DO-NOT-ECHO' not in result.text


@pytest.mark.parametrize('kind', ['duplicate_next_page', 'incomplete', 'wrong_page', 'partial_phone'])
def test_phone_lookup_fails_closed_on_incomplete_or_nonunique_results(client, owner, configured, monkeypatch, kind):
    calls = []
    @contextmanager
    def session(*args):
        def response(request):
            calls.append(request)
            row = {'id': 7, 'username': 'subscriber', 'phone': '07500000000'}
            if kind == 'partial_phone': row['phone'] = '07500000001'
            if kind == 'duplicate_next_page' and len(calls) == 2:
                row = {'id': 8, 'username': 'other', 'phone': '+9647500000000'}
            result = {'data': [row], 'total': 2 if kind in ('duplicate_next_page', 'incomplete') else 1,
                      'per_page': 1 if kind == 'duplicate_next_page' else 100,
                      'current_page': 2 if kind == 'wrong_page' else len(calls)}
            return httpx.Response(200, json=result)
        with httpx.Client(transport=httpx.MockTransport(response)) as remote:
            yield remote, {}
    monkeypatch.setattr(sas4, 'sas4_session', session)
    challenge = client.get('/api/client/login-options').json()['challenge_id']
    result = client.post('/api/client/login', headers=HEADERS, json={
        'phone': '07500000000', 'password': 'PPPOE-PASSWORD', 'challenge_id': challenge})
    assert result.status_code == 401 and 'set-cookie' not in result.headers
    assert len(calls) == (2 if kind == 'duplicate_next_page' else 1)


@pytest.fixture
def shared_phone_password(monkeypatch):
    from dataclasses import replace
    configured_settings = replace(portal.settings, client_phone_password='123')
    monkeypatch.setattr(portal, 'settings', configured_settings)
    return configured_settings


def shared_phone_login(client):
    options = client.get('/api/client/login-options').json()
    assert options['shared_phone_password'] is True
    assert '123' not in options.values()
    return client.post('/api/client/login', headers=HEADERS, json={
        'phone': '07500000000', 'password': '123', 'challenge_id': options['challenge_id']})


def test_shared_phone_password_is_portal_only_and_session_stays_customer_scoped(client, owner, configured, monkeypatch, shared_phone_password):
    phone_directory(monkeypatch, [{'id': 7, 'username': 'subscriber', 'phone': '07500000000'}])
    native_calls = []
    original = portal.ucp
    def ucp(remote, route, token=None, body=None):
        native_calls.append(route)
        return original(remote, route, token, body)
    monkeypatch.setattr(portal, 'ucp', ucp)
    result = shared_phone_login(client)
    assert result.status_code == 200 and result.json() == {'authenticated': True}
    account = client.get('/api/client/account')
    assert account.status_code == 200 and account.json()['username'] == 'subscriber'
    assert account.json()['can_recharge'] is True
    assert native_calls == ['resources/config']
    assert 'PRIVATE' not in account.text
    assert client.get('/api/auth/me').status_code == 401
    assert client.get('/api/users').status_code == 401
    with SessionLocal() as db:
        session = db.query(ClientPortalSession).one()
        assert '07500000000' not in session.encrypted_token
        assert portal.PHONE_SESSION_PREFIX not in session.encrypted_token
    assert client.post('/api/client/logout', headers=HEADERS).status_code == 200
    assert client.get('/api/client/account').status_code == 401


@pytest.mark.parametrize('change', ['disabled', 'rotated', 'phone_changed', 'account_disabled'])
def test_shared_phone_sessions_expire_when_operator_access_or_customer_changes(client, owner, configured, monkeypatch, shared_phone_password, change):
    from dataclasses import replace
    phone_directory(monkeypatch, [{'id': 7, 'username': 'subscriber', 'phone': '07500000000'}])
    assert shared_phone_login(client).status_code == 200
    if change in ('disabled', 'rotated'):
        monkeypatch.setattr(portal, 'settings', replace(shared_phone_password, client_phone_password='' if change == 'disabled' else '456'))
    elif change == 'phone_changed':
        monkeypatch.setattr(portal, 'validate_customer', lambda *a: {'phone': '07500000001'})
    else:
        configured['enabled'] = False
    assert client.get('/api/client/account').status_code == 401


def test_wrong_shared_password_does_not_lookup_customers(client, owner, configured, monkeypatch, shared_phone_password):
    monkeypatch.setattr(portal, 'phone_login_identity', lambda *a: pytest.fail('Wrong password must not query customer identities'))
    challenge = client.get('/api/client/login-options').json()['challenge_id']
    result = client.post('/api/client/login', headers=HEADERS, json={
        'phone': '07500000000', 'password': '456', 'challenge_id': challenge})
    assert result.status_code == 401 and 'set-cookie' not in result.headers


def test_username_login_still_uses_sas4_password_when_shared_phone_login_is_enabled(client, owner, configured, shared_phone_password):
    response, _ = login(client)
    assert response.status_code == 200
    assert client.get('/api/client/account').status_code == 200


def test_native_sas4_token_cannot_masquerade_as_local_phone_session(client, owner, configured, monkeypatch, shared_phone_password):
    original = portal.ucp
    def ucp(remote, route, token=None, body=None):
        if route == 'auth/login':
            return {'status': 200, 'token': portal.PHONE_SESSION_PREFIX + '{}'}
        return original(remote, route, token, body)
    monkeypatch.setattr(portal, 'ucp', ucp)
    challenge = client.get('/api/client/login-options').json()['challenge_id']
    result = client.post('/api/client/login', headers=HEADERS, json={
        'username': 'subscriber', 'password': 'PPPOE-PASSWORD', 'challenge_id': challenge})
    assert result.status_code == 401 and 'set-cookie' not in result.headers


@pytest.mark.parametrize('value,prefill', [('', False), ('123', True), ('another-portal-code', False)])
def test_only_the_explicit_fixed_123_code_is_prefilled(client, owner, configured, monkeypatch, value, prefill):
    from dataclasses import replace
    monkeypatch.setattr(portal, 'settings', replace(portal.settings, client_phone_password=value))
    options = client.get('/api/client/login-options').json()
    assert options['prefill_phone_password'] is prefill
    assert options['shared_phone_password'] is bool(value)
    assert value not in options.values()
