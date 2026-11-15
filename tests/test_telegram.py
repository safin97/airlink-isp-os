from sqlalchemy import select
import pytest
from airlink import telegram
from airlink.db import SessionLocal
from airlink.models import TelegramSettings, TelegramNotification, Tower, Device, now
from airlink.security import cipher
from monitoring.alerts import evaluate
from test_api import user

PATH = '/api/integrations/telegram'
TOKEN = '123456:private_test_token'

def test_settings_permissions_encryption_and_test(client, owner, monkeypatch):
    _, manager = user(client, owner, 'viewer')
    assert client.get(PATH, headers=manager).status_code == 403
    assert client.put(PATH, headers=manager, json={'chat_id':'123', 'bot_token':TOKEN}).status_code == 403
    assert client.post(PATH + '/test', headers=manager).status_code == 403
    result = client.put(PATH, headers=owner, json={'enabled':True, 'chat_id':'-123', 'bot_token':TOKEN})
    assert result.status_code == 200 and TOKEN not in result.text
    with SessionLocal() as db:
        row = db.get(TelegramSettings, 1)
        assert TOKEN not in row.encrypted_token
        assert cipher().decrypt(row.encrypted_token.encode()).decode() == TOKEN
    sent=[]
    monkeypatch.setattr(telegram, 'send', lambda row, message: sent.append(message))
    assert client.post(PATH + '/test', headers=owner).status_code == 200
    assert len(sent) == 1
    assert client.put(PATH, headers=owner, json={'enabled':False, 'chat_id':'-123'}).json()['has_token']
    assert client.put(PATH, headers=owner, json={'chat_id':'https://evil', 'bot_token':TOKEN}).status_code == 422


def test_down_recovery_dedup_and_retry(client, owner, monkeypatch):
    client.put(PATH, headers=owner, json={'enabled':True, 'chat_id':'123', 'bot_token':TOKEN})
    with SessionLocal() as db:
        tower=Tower(name='T'); db.add(tower); db.flush()
        device=Device(name='D', tower_id=tower.id, ip_address='192.0.2.1', status='offline', last_poll=now(), poll_interval=60, cpu_threshold=90)
        db.add(device); db.flush()
        evaluate(db,device,None); db.commit()
        evaluate(db,device,None); db.commit()
        assert len(db.scalars(select(TelegramNotification)).all()) == 1
        def fail(*args): raise RuntimeError('Telegram unavailable')
        monkeypatch.setattr(telegram,'send',fail)
        telegram.dispatch(db)
        item=db.scalar(select(TelegramNotification))
        assert item.attempts == 1 and item.sent_at is None
        sent=[]
        monkeypatch.setattr(telegram,'send',lambda row, message: sent.append(message))
        telegram.dispatch(db)
        assert sent == []
        item.next_attempt=now(); db.commit(); telegram.dispatch(db)
        telegram.dispatch(db)
        assert len(sent) == 1 and 'DOWN / TIMEOUT' in sent[0]
        device.status='online'; evaluate(db,device,None); db.commit(); telegram.dispatch(db)
        assert len(sent) == 2 and 'RECOVERED' in sent[1]
        db.get(TelegramSettings,1).enabled=False
        device.status='offline'; evaluate(db,device,None); db.commit()
        assert len(db.scalars(select(TelegramNotification)).all()) == 2


def test_manager_connections_and_delivery_are_isolated(client, owner, monkeypatch):
    from airlink.models import User
    first_id, first = user(client, owner, 'manager', 'first')
    second_id, second = user(client, owner, 'manager', 'second')
    first_path = PATH + '/accounts/' + first_id
    second_path = PATH + '/accounts/' + second_id
    for path, chat in ((PATH, '100'), (first_path, '101'), (second_path, '102')):
        response = client.put(path, headers=owner, json={'enabled':True, 'chat_id':chat, 'bot_token':TOKEN})
        assert response.status_code == 200, response.text
    assert client.get(first_path, headers=owner).json()['chat_id'] == '101'
    assert client.get(second_path, headers=owner).json()['chat_id'] == '102'
    assert client.get(PATH, headers=owner).json()['chat_id'] == '100'
    assert client.put(first_path, headers=first, json={'chat_id':'999'}).status_code == 403
    sent=[]
    monkeypatch.setattr(telegram, 'send', lambda row, msg: sent.append(row.chat_id))
    assert client.post(first_path + '/test', headers=owner).status_code == 200
    assert sent == ['101']
    sent.clear()
    with SessionLocal() as db:
        tower=Tower(name='Private tower', manager_id=first_id); db.add(tower); db.flush()
        device=Device(name='Private device', tower_id=tower.id, ip_address='192.0.2.1', status='offline', last_poll=now(), poll_interval=60, cpu_threshold=90)
        db.add(device); db.flush(); evaluate(db,device,None); db.commit()
        assert {item.user_id for item in db.scalars(select(TelegramNotification))} == {first_id, db.scalar(select(User).where(User.role=='owner')).id}
        telegram.dispatch(db)
        assert sorted(sent) == ['100', '101']
        sent.clear()
        device.status='online'; evaluate(db,device,None); db.commit()
        # Recheck tower access immediately before delivering an already queued event.
        tower.manager_id=second_id; db.commit(); telegram.dispatch(db)
        assert sent == ['100']
    # Saving one account does not erase another account's queue or destination.
    assert client.put(first_path, headers=owner, json={'enabled':False,'chat_id':'101'}).status_code == 200
    assert client.get(second_path, headers=owner).json()['enabled'] is True


def test_personal_message_templates_and_rendering(client, owner):
    manager_id, manager = user(client, owner, 'manager', 'templates-manager')
    path = PATH + '/accounts/' + manager_id + '/messages'
    assert client.get(path, headers=manager).status_code == 403
    assert client.get(PATH, headers=manager).status_code == 403
    defaults = client.get(path, headers=owner)
    assert defaults.status_code == 200
    down = 'Lost {device_name} at {tower_name} ({ip_address}) — {status}'
    recovery = 'Back: {device_name} at {time}'
    response = client.put(path, headers=owner, json={'down_message':down, 'recovery_message':recovery})
    assert response.status_code == 200, response.text
    assert client.get(PATH + '/messages', headers=owner).json()['down_message'] == telegram.DEFAULT_MESSAGE
    assert client.get(path, headers=owner).json()['down_message'] == down
    for invalid in (' ', '{password}', 'x'*1001):
        assert client.put(path, headers=owner, json={'down_message':invalid,'recovery_message':recovery}).status_code == 422
    client.put(PATH + '/accounts/' + manager_id, headers=owner, json={'enabled':True, 'chat_id':'123', 'bot_token':TOKEN})
    with SessionLocal() as db:
        tower=Tower(name='North', manager_id=manager_id); db.add(tower); db.flush()
        device=Device(name='Router {status}', tower_id=tower.id, ip_address='192.0.2.10', status='offline', last_poll=now(), poll_interval=60, cpu_threshold=90)
        db.add(device); db.flush(); evaluate(db,device,None); db.commit()
        item=db.scalar(select(TelegramNotification))
        assert item.message == 'Lost Router {status} at North (192.0.2.10) — DOWN / TIMEOUT'
        device.status='online'; evaluate(db,device,None); db.commit()
        assert any(item.message.startswith('Back: Router {status} at ') for item in db.scalars(select(TelegramNotification)))


@pytest.mark.parametrize('language', ['en', 'ku', 'ar'])
def test_notification_language_delivery_and_account_isolation(client, owner, monkeypatch, language):
    manager_id, _ = user(client, owner, 'manager', 'localized-manager')
    path = PATH + '/accounts/' + manager_id
    catalog = client.get(path + '/messages', headers=owner).json()
    assert catalog['language'] == 'en'
    localized = catalog['languages'][language]
    template = localized['default_message']
    response = client.put(path + '/messages', headers=owner, json={
        'language': language, 'down_message': template, 'recovery_message': template})
    assert response.status_code == 200, response.text
    saved = client.get(path + '/messages', headers=owner).json()
    assert saved['language'] == language and saved['default_message'] == template
    assert client.get(PATH + '/messages', headers=owner).json()['language'] == 'en'
    # Older clients that omit language must preserve the saved selection.
    assert client.put(path + '/messages', headers=owner, json={
        'down_message': template, 'recovery_message': template}).json()['language'] == language
    assert client.put(path + '/messages', headers=owner, json={
        'language': 'unsupported', 'down_message': template, 'recovery_message': template}).status_code == 422
    client.put(path, headers=owner, json={'enabled': True, 'chat_id': '123', 'bot_token': TOKEN})
    sent = []
    monkeypatch.setattr(telegram, 'send', lambda row, message: sent.append(message))
    assert client.post(path + '/test', headers=owner).status_code == 200
    assert sent.pop() == localized['test_message']
    with SessionLocal() as db:
        tower = Tower(name='North Tower', manager_id=manager_id)
        db.add(tower); db.flush()
        device = Device(name='Router', tower_id=tower.id, ip_address='192.0.2.10',
                        status='offline', last_poll=now(), poll_interval=60, cpu_threshold=90)
        db.add(device); db.flush()
        evaluate(db, device, None); db.commit(); telegram.dispatch(db)
        device.status = 'online'
        evaluate(db, device, None); db.commit(); telegram.dispatch(db)
    assert len(sent) == 2
    assert localized['down_status'] in sent[0]
    assert localized['recovery_status'] in sent[1]
    assert all('North Tower' in message and '192.0.2.10' in message for message in sent)
    assert all('{status}' not in message and '{tower_name}' not in message for message in sent)


def test_language_migration_preserves_custom_templates(tmp_path):
    import importlib.util
    from pathlib import Path
    from sqlalchemy import create_engine, text
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    spec = importlib.util.spec_from_file_location('telegram_language_migration',
        Path(__file__).resolve().parents[1] / 'database/versions/d94ec361752b_telegram_language.py')
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine('sqlite:///' + str(tmp_path / 'migration.sqlite'))
    with engine.begin() as connection:
        connection.execute(text('CREATE TABLE telegram_message_templates '
            '(user_id VARCHAR(36) PRIMARY KEY, down_message TEXT NOT NULL, recovery_message TEXT NOT NULL)'))
        connection.execute(text("INSERT INTO telegram_message_templates VALUES ('existing', 'Custom down', 'Custom up')"))
        migration.op = Operations(MigrationContext.configure(connection))
        migration.upgrade()
        assert tuple(connection.execute(text('SELECT down_message, recovery_message, language '
            'FROM telegram_message_templates')).one()) == ('Custom down', 'Custom up', 'en')
        migration.downgrade()
        assert tuple(connection.execute(text('SELECT down_message, recovery_message '
            'FROM telegram_message_templates')).one()) == ('Custom down', 'Custom up')
    engine.dispose()
