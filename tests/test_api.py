import os
from datetime import timedelta
import pytest
from sqlalchemy import select
from airlink.db import SessionLocal
from airlink.models import SNMPProfile, User, Alert, Device, Metric, now
from airlink.security import hasher, cipher
from conftest import PASSWORD


def user(client, owner, role, name=None):
    name = name or role
    r=client.post('/api/users', headers=owner, json={'username':name,'password':PASSWORD,'role':role})
    assert r.status_code == 201, r.text
    identity=r.json()['id']
    login=client.post('/api/auth/login',json={'username':name,'password':PASSWORD})
    return identity, {'Authorization':'Bearer '+login.json()['access_token']}


def tower(client, owner, name='North', manager=None):
    r=client.post('/api/towers', headers=owner,json={'name':name,'manager_id':manager})
    assert r.status_code==201,r.text
    return r.json()['id']


def device(client, owner, tid, ip='192.0.2.1'):
    r=client.post('/api/devices',headers=owner,json={'name':'Router','ip_address':ip,'tower_id':tid})
    assert r.status_code==201,r.text
    return r.json()['id']


def test_setup_single_owner_and_no_password_leak(client, owner):
    r=client.post('/api/setup',json={'username':'other','password':PASSWORD,'confirm_password':PASSWORD,'token':os.environ['AIRLINK_BOOTSTRAP_TOKEN']})
    assert r.status_code==409
    assert 'password' not in client.get('/api/auth/me',headers=owner).text
    with SessionLocal() as db:
        assert db.scalar(select(User)).password_hash.startswith('$argon2id$')


def test_setup_rejects_wrong_token_and_weak_password(client):
    data={'username':'owner','password':PASSWORD,'confirm_password':PASSWORD,'token':'x'*40}
    assert client.post('/api/setup',json=data).status_code==403
    data.update(password='password',confirm_password='password')
    assert client.post('/api/setup',json=data).status_code==422


def test_unauthenticated_and_rate_limit(client, owner):
    assert client.get('/api/devices').status_code==401
    results=[client.post('/api/auth/login',json={'username':'missing','password':'wrong'}).status_code for _ in range(11)]
    assert results[-1]==429


def test_refresh_rotation_reuse_revokes_family(client, owner):
    old=client.cookies.get('airlink_refresh')
    first=client.post('/api/auth/refresh',headers={'X-AirLink-Request':'1'})
    assert first.status_code==200
    assert client.cookies.get('airlink_refresh')!=old
    client.cookies.clear()
    client.cookies.set('airlink_refresh',old,path='/api/auth')
    assert client.post('/api/auth/refresh',headers={'X-AirLink-Request':'1'}).status_code==401
    assert client.get('/api/auth/me',headers={'Authorization':'Bearer '+first.json()['access_token']}).status_code==401


def test_refresh_requires_custom_header(client, owner):
    assert client.post('/api/auth/refresh').status_code==403


def test_manager_scope_cannot_reassign_or_cross_towers(client, owner):
    mid, manager=user(client,owner,'manager')
    mine=tower(client,owner,manager=mid)
    other=tower(client,owner,'South')
    did=device(client,owner,other)
    assert [x['id'] for x in client.get('/api/towers',headers=manager).json()]==[mine]
    assert client.get(f'/api/devices/{did}/metrics',headers=manager).status_code==404
    assert client.post('/api/devices',headers=manager,json={'name':'X','tower_id':other,'ip_address':'192.0.2.2'}).status_code==404
    assert client.put('/api/towers/'+mine,headers=manager,json={'name':'X','manager_id':None}).status_code==403
    assert client.post('/api/users',headers=manager,json={'username':'evil','role':'owner','password':PASSWORD}).status_code==403
    assert client.get('/api/updates',headers=manager).status_code==403


def test_technician_only_assigned_devices_and_alerts(client, owner):
    uid, tech=user(client,owner,'technician')
    tid=tower(client,owner)
    a=device(client,owner,tid)
    b=device(client,owner,tid,'192.0.2.2')
    client.put(f'/api/users/{uid}/devices/{a}',headers=owner)
    assert [d['id'] for d in client.get('/api/devices',headers=tech).json()]==[a]
    assert client.get(f'/api/devices/{b}/metrics',headers=tech).status_code==404
    with SessionLocal() as db:
        alert=Alert(device_id=b,kind='test',severity='warning',message='test')
        db.add(alert);db.commit();alert_id=alert.id
    assert client.post(f'/api/alerts/{alert_id}/acknowledge',headers=tech).status_code==404
    assert client.delete('/api/devices/'+a,headers=tech).status_code==403


def test_viewer_is_read_only(client, owner):
    _,viewer=user(client,owner,'viewer')
    tid=tower(client,owner)
    assert client.get('/api/towers',headers=viewer).status_code==200
    assert client.delete('/api/towers/'+tid,headers=viewer).status_code==403


def test_cross_sector_validation_and_delete_dependency(client, owner):
    a=tower(client,owner)
    b=tower(client,owner,'South')
    sid=client.post('/api/sectors',headers=owner,json={'name':'Sector','tower_id':a}).json()['id']
    assert client.post('/api/devices',headers=owner,json={'name':'D','tower_id':b,'sector_id':sid,'ip_address':'192.0.2.1'}).status_code==422
    assert client.delete('/api/towers/'+a,headers=owner).status_code==409
    assert client.delete('/api/sectors/'+sid,headers=owner).status_code==204
    assert client.delete('/api/towers/'+a,headers=owner).status_code==204


def test_snmp_secrets_encrypted_not_returned(client, owner):
    r=client.post('/api/snmp-profiles',headers=owner,json={'name':'Secure profile','username':'monitor','auth_key':'AuthKey-very-secret','priv_key':'PrivKey-very-secret'})
    assert r.status_code==201
    assert 'secret' not in r.text and 'encrypted_credentials' not in r.text
    with SessionLocal() as db:
        profile=db.scalar(select(SNMPProfile))
        assert 'AuthKey' not in profile.encrypted_credentials
        assert b'AuthKey-very-secret' in cipher().decrypt(profile.encrypted_credentials.encode())


def test_no_fabricated_metrics_and_stale_status(client, owner):
    tid=tower(client,owner)
    did=device(client,owner,tid)
    summary=client.get('/api/dashboard',headers=owner).json()
    assert summary['connected_clients'] is None and summary['availability_24h'] is None
    assert summary['online']==0 and summary['unknown']==1
    with SessionLocal() as db:
        d=db.get(Device,did);d.status='online';d.last_poll=now()-timedelta(hours=1)
        db.add(Metric(device_id=did,values={'icmp_up':True}));db.add(Metric(device_id=did,values={'icmp_up':False}));db.commit()
    assert client.get('/api/devices',headers=owner).json()[0]['status']=='unknown'
    assert client.get('/api/dashboard',headers=owner).json()['availability_24h']==50


@pytest.mark.parametrize('address',['127.0.0.1','0.0.0.0','224.0.0.1','bad','169.254.1.1'])
def test_invalid_monitoring_addresses(client,owner,address):
    tid=tower(client,owner)
    assert client.post('/api/devices',headers=owner,json={'name':'bad','tower_id':tid,'ip_address':address}).status_code==422


def test_authenticated_websocket(client,owner):
    with client.websocket_connect('/api/ws') as ws:
        ws.send_json({'token':owner['Authorization'].split()[1]})
        assert ws.receive_json()['devices']==0


def test_report_escapes_spreadsheet_formula(client,owner):
    tid=tower(client,owner)
    client.post('/api/devices',headers=owner,json={'name':'=HYPERLINK("bad")','tower_id':tid,'ip_address':'192.0.2.2'})
    r=client.get('/api/reports/availability.csv',headers=owner)
    assert "'=HYPERLINK" in r.text


def test_logout_revokes_access_even_without_refresh_cookie(client,owner):
    client.cookies.clear()
    assert client.post('/api/auth/logout',headers=owner).status_code==200
    assert client.get('/api/auth/me',headers=owner).status_code==401


def test_empty_device_address_rejected(client,owner):
    tid=tower(client,owner)
    assert client.post('/api/devices',headers=owner,json={'name':'D','tower_id':tid,'ip_address':''}).status_code==422


@pytest.mark.parametrize('role', ['manager', 'technician', 'viewer'])
def test_update_checks_and_installation_are_owner_only(client, owner, monkeypatch, role):
    _, headers = user(client, owner, role)
    from airlink import api
    def forbidden(*args, **kwargs):
        pytest.fail('Non-owner reached the privileged update controller')
    monkeypatch.setattr(api, 'broker', forbidden)
    assert client.get('/api/updates', headers=headers).status_code == 403
    for action in ('check', 'download', 'verify', 'install', 'schedule'):
        assert client.post('/api/updates/' + action, headers=headers, json={}).status_code == 403

@pytest.mark.parametrize('role', ['manager', 'technician', 'viewer'])
def test_restart_is_owner_only(client, owner, monkeypatch, role):
    _, headers = user(client, owner, role)
    from airlink import api
    monkeypatch.setattr(api, 'broker', lambda *args: pytest.fail('Unauthorized restart'))
    assert client.post('/api/system/restart', json={'confirm': True}).status_code == 401
    assert client.post('/api/system/restart', headers=headers, json={'confirm': True}).status_code == 403


def test_owner_restart_confirmation_and_audit(client, owner, monkeypatch):
    from airlink import api
    calls=[]
    def restart(action, payload):
        calls.append((action,payload))
        return {'status':'restart_requested','boot_id':'old-boot','delay_seconds':5}
    monkeypatch.setattr(api, 'broker', restart)
    for payload in ({}, {'confirm':False}, {'confirm':'true'}):
        assert client.post('/api/system/restart',headers=owner,json=payload).status_code == 422
    assert not calls
    response=client.post('/api/system/restart',headers=owner,json={'confirm':True})
    assert response.status_code == 202
    assert calls == [('system.restart',{'confirm':True})]
    assert any(row['action']=='system.restart' for row in client.get('/api/audit',headers=owner).json())
