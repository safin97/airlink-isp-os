from datetime import timedelta
from types import SimpleNamespace as NS
import pytest
from sqlalchemy import select
from airlink import recharge_telegram as rt, customer_telegram as ct
from airlink.db import SessionLocal
from airlink.models import now
from test_recharge_telegram import receipts, deliver
from test_telegram_account import telegram, clear_rate

PATH='/api/integrations/recharge-telegram'


def enable(client,owner,receipts,monkeypatch,hours):
    record=receipts[1]
    record['expiration']=(now()+timedelta(hours=hours)).isoformat()
    calls=[]
    def clients(*args,**kwargs):
        calls.append(kwargs['page'])
        return {'clients':[{'id':7,'username':record['username'],'profile':record['profile_name'],
                            'enabled':True,'expiration':record['expiration']}], 'page':1, 'last_page':1}
    monkeypatch.setattr(ct.sas4,'fetch_clients',clients)
    assert client.put(PATH+'/expiry',headers=owner,json={'enabled':True}).status_code==200
    return calls


@pytest.mark.parametrize('hours,expected',[(73,None),(71,'expiry_3days'),(49,'expiry_3days'),(47,None),(1,None),(-1,'expired'),(-23,'expired'),(-25,None)])
def test_expiry_windows_and_once_per_expiry_date(client,owner,receipts,monkeypatch,hours,expected):
    calls=enable(client,owner,receipts,monkeypatch,hours)
    with SessionLocal() as db:
        rt.scan_expiry(db)
        schedule=db.get(rt.ExpirySchedule,1)
        schedule.next_check=now()-timedelta(seconds=1)
        db.commit()
        rt.scan_expiry(db)
        events=db.scalars(select(rt.Event)).all()
        assert len(events)==int(expected is not None)
        if expected:
            event=events[0]
            assert event.kind==expected
            rt.deliver(db,event)
            assert event.status=='sent'
            rt.deliver(db,event)
            sent=[c[1].message for c in receipts[0][1] if isinstance(c,tuple) and c[0]=='send']
            assert len(sent)==1 and rt.EXPIRY_LABELS['en'][expected] in sent[0]
            assert 'Recharge successful' not in sent[0] and 'New expiry' not in sent[0]
            assert 'PRIVATE' not in sent[0]
    assert calls==[1,1]


@pytest.mark.parametrize('change',['renewed','disabled','late','alerts_off'])
def test_stale_expiry_alerts_are_cancelled(client,owner,receipts,monkeypatch,change):
    enable(client,owner,receipts,monkeypatch,71)
    with SessionLocal() as db:
        rt.scan_expiry(db)
        event=db.scalar(select(rt.Event))
        if change=='renewed': receipts[1]['expiration']=(now()+timedelta(days=30)).isoformat()
        if change=='disabled': receipts[1]['enabled']=False
        if change=='late': monkeypatch.setattr(rt,'now',lambda: now()+timedelta(days=2))
        if change=='alerts_off': db.get(rt.ExpirySchedule,1).enabled=False; db.commit()
        rt.deliver(db,event)
        assert event.status=='cancelled'
    assert not [c for c in receipts[0][1] if isinstance(c,tuple) and c[0]=='send']


def test_expiry_off_by_default_and_scan_failures_do_not_send(client,owner,receipts,monkeypatch):
    assert not client.get(PATH+'/expiry',headers=owner).json()['enabled']
    def failed(*args,**kwargs): raise RuntimeError('PRIVATE_PROVIDER_ERROR')
    monkeypatch.setattr(ct.sas4,'fetch_clients',failed)
    with SessionLocal() as db: rt.scan_expiry(db)
    assert client.put(PATH+'/expiry',headers=owner,json={'enabled':True}).status_code==200
    with SessionLocal() as db:
        rt.scan_expiry(db)
        assert db.scalar(select(rt.Event)) is None
    response=client.get(PATH+'/expiry',headers=owner)
    assert response.json()['last_error'] and 'PRIVATE' not in response.text


@pytest.mark.parametrize('language',['en','ar','ku'])
@pytest.mark.parametrize('kind',['expiry_3days','expired'])
def test_expiry_templates_edit_preview_reset(client,owner,language,kind):
    path=PATH+'/templates/'+language+'/'+kind
    result=client.get(path,headers=owner)
    assert result.status_code==200 and rt.EXPIRY_LABELS[language][kind] in result.json()['preview']
    assert client.put(path,headers=owner,json={'text':'NOTICE {username}: {expiration}'}).status_code==200
    assert client.get(path,headers=owner).json()['customized']
    assert not client.delete(path,headers=owner).json()['customized']


def test_scans_paginate_and_pause_after_complete_pass(client,owner,receipts,monkeypatch):
    enable(client,owner,receipts,monkeypatch,71)
    pages=[]
    def clients(*args,**kwargs):
        page=kwargs['page']; pages.append(page)
        return {'clients':[],'page':page,'last_page':2}
    monkeypatch.setattr(ct.sas4,'fetch_clients',clients)
    with SessionLocal() as db:
        rt.scan_expiry(db)
        assert db.get(rt.ExpirySchedule,1).page==2
        rt.scan_expiry(db)
        assert pages==[1]
        db.get(rt.ExpirySchedule,1).next_check=now()-timedelta(seconds=1); db.commit()
        rt.scan_expiry(db)
        assert pages==[1,2] and db.get(rt.ExpirySchedule,1).page==1


def test_account_expiry_selection_suppresses_old_bot_reminder(client,owner,receipts):
    with SessionLocal() as db:
        db.add(rt.ExpirySchedule(id=1,enabled=True)); db.commit()
        event=NS(kind='expiry',status='pending')
        ct.deliver(db,event)
        assert event.status=='cancelled'


def test_expiry_alerts_continue_when_recharge_notifications_are_disabled(client,owner,receipts,monkeypatch):
    enable(client,owner,receipts,monkeypatch,71)
    with SessionLocal() as db:
        rt.scan_expiry(db)
        event_id=db.scalar(select(rt.Event)).id
    assert client.put(PATH,headers=owner,json={'enabled':False}).status_code==200
    assert deliver(event_id)[0]=='sent'
