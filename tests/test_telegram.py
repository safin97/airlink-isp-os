from sqlalchemy import select
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
    for headers, chat in ((owner, '100'), (first, '101'), (second, '102')):
        response = client.put(PATH, headers=headers, json={'enabled':True, 'chat_id':chat, 'bot_token':TOKEN})
        assert response.status_code == 200, response.text
    assert client.get(PATH, headers=first).json()['chat_id'] == '101'
    assert client.get(PATH, headers=second).json()['chat_id'] == '102'
    assert client.get(PATH, headers=owner).json()['chat_id'] == '100'
    assert client.put(PATH, headers=first, json={'chat_id':'999', 'user_id':second_id}).status_code == 422
    sent=[]
    monkeypatch.setattr(telegram, 'send', lambda row, msg: sent.append(row.chat_id))
    assert client.post(PATH + '/test', headers=first).status_code == 200
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
    assert client.put(PATH, headers=first, json={'enabled':False,'chat_id':'101'}).status_code == 200
    assert client.get(PATH, headers=second).json()['enabled'] is True
