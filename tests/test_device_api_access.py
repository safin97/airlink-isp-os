import json
from sqlalchemy import select
from airlink import device_access, tower_api, sas4_reports
from airlink.db import SessionLocal
from airlink.models import User, CustomerProbeSettings, SAS4UserConnection
from airlink.security import cipher
from test_api import user, tower

PATH = '/api/device-api-access'


def test_tower_assignment_is_used_by_management_and_secrets_stay_private(client, owner):
    tid = tower(client, owner)
    body = {'scope':'tower','target_id':tid,'username':'device-admin','password':'private-device-password','protocol':'both'}
    response = client.put(PATH, headers=owner, json=body)
    assert response.status_code == 200, response.text
    assert response.json()['protocol'] == 'both'
    assert response.json()['has_password'] is True and 'private-device-password' not in response.text
    with SessionLocal() as db:
        saved = tower_api.configuration(db, tid)
        assert saved['enabled'] and saved['api_username'] == 'device-admin' and saved['api_password'] == body['password']
    assert 'private-device-password' not in client.get(PATH, headers=owner).text
    assert client.put(PATH, headers=owner, json={**body,'password':None}).status_code == 200
    assert client.put(PATH, headers=owner, json={**body,'username':'different','password':None}).status_code == 422
    _, manager = user(client, owner, 'manager')
    assert client.get(PATH, headers=manager).status_code == 403
    assert client.put(PATH, headers=manager, json=body).status_code == 403


def test_isp_manager_assignment_is_encrypted_and_bound_to_sas4_connection(client, owner, monkeypatch):
    owner_id = client.get('/api/auth/me', headers=owner).json()['id']
    with SessionLocal() as db:
        db.add(SAS4UserConnection(user_id=owner_id,username='sas-owner', encrypted_password=cipher().encrypt(b'sas-secret').decode()))
        db.add(CustomerProbeSettings(user_id=owner_id,encrypted_settings=cipher().encrypt(json.dumps({'community':'existing-snmp'}).encode()).decode()))
        db.commit()
    monkeypatch.setattr(sas4_reports, 'fetch_managers', lambda *args,**kw: [{'id':4,'username':'North manager'}])
    body = {'scope':'isp_manager','target_id':'4','username':'device-reader','password':'private-manager-device-password','protocol':'both'}
    response = client.put(PATH, headers=owner, json=body)
    assert response.status_code == 200, response.text
    assert response.json()['protocol'] == 'both'
    assert 'private-manager-device-password' not in response.text
    assert client.put(PATH, headers=owner, json={**body,'password':None}).status_code == 200
    listing = client.get(PATH, headers=owner)
    assert listing.json()['isp_managers'][0]['name'] == 'North manager'
    assert 'private-manager-device-password' not in listing.text
    assert client.put(PATH, headers=owner, json={**body,'target_id':'999'}).status_code == 404
    with SessionLocal() as db:
        account = db.get(User, owner_id)
        assert device_access.manager_configuration(db, account, 4)['api_password'] == body['password']
        row = db.get(CustomerProbeSettings, owner_id)
        assert body['password'] not in row.encrypted_settings
        assert json.loads(cipher().decrypt(row.encrypted_settings.encode()))['community'] == 'existing-snmp'
        assert cipher().decrypt(db.get(SAS4UserConnection, owner_id).encrypted_password.encode()) == b'sas-secret'
        db.get(SAS4UserConnection, owner_id).username = 'different-sas-account'; db.commit()
        assert device_access.manager_configuration(db, account, 4) is None
    assert client.get(PATH, headers=owner).json()['isp_managers'] == []
