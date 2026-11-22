"""Inventory query growth and access/freshness regressions."""
import json
from datetime import timedelta
from sqlalchemy import event
from airlink import api, live_updates
from airlink.db import SessionLocal, engine
from airlink.models import User, Tower, TowerPlace, Place, Sector, Device, DeviceAssignment, TowerAPISettings, Metric, now
from airlink.security import cipher
from test_api import user


def test_inventory_queries_are_bounded_with_many_towers(client, owner):
    oid = client.get('/api/auth/me', headers=owner).json()['id']
    with SessionLocal() as db:
        place = Place(name='North'); db.add(place); db.flush()
        for i in range(40):
            tower = Tower(name=f'Tower {i:02}'); db.add(tower); db.flush()
            db.add(TowerPlace(tower_id=tower.id, place_id=place.id))
            sector = Sector(tower_id=tower.id, name='Radio sector'); db.add(sector)
            db.add(TowerAPISettings(tower_id=tower.id, encrypted_credentials=cipher().encrypt(json.dumps({
                'enabled': True, 'api_username': 'reader', 'api_password': 'must-not-be-public'}).encode()).decode()))
            device = Device(tower_id=tower.id, name='Radio', ip_address=f'192.0.2.{i+1}',
                            enabled=True, status='online', last_poll=now())
            db.add(device); db.flush()
            db.add(Metric(device_id=device.id, values={'api_status': 'connected', 'signal_dbm': -62}))
        db.commit()
    for reader, limit in ((api.towers, 3), (api.devices, 2)):
        with SessionLocal() as db:
            account = db.get(User, oid)
            statements = []
            def record(*args): statements.append(1)
            event.listen(engine, 'before_cursor_execute', record)
            try: rows = reader(user=account, db=db)
            finally: event.remove(engine, 'before_cursor_execute', record)
        assert len(rows) == 40
        assert len(statements) <= limit
        assert 'must-not-be-public' not in json.dumps(rows, default=str)
        if reader == api.towers:
            assert all(row['sector_count'] == 1 and row['place_id'] == place.id and row['status'] == 'online' for row in rows)
            assert all(row['has_api_password'] and row['api_username'] == 'reader' for row in rows)
        else:
            assert all(row['api_status'] == 'connected' and row['telemetry']['signal_dbm'] == -62 for row in rows)


def test_batched_inventory_preserves_manager_and_technician_scope(client, owner):
    mid, manager = user(client, owner, 'manager')
    tech_id, technician = user(client, owner, 'technician')
    with SessionLocal() as db:
        shared = Tower(name='Assigned', manager_id=mid)
        private = Tower(name='Private'); empty = Tower(name='Empty', manager_id=mid)
        db.add_all([shared, private, empty]); db.flush()
        visible = Sector(tower_id=shared.id, name='Assigned sector')
        hidden = Sector(tower_id=shared.id, name='Unassigned sector')
        db.add_all([visible, hidden]); db.flush()
        assigned = Device(name='Assigned radio', ip_address='192.0.2.1', tower_id=shared.id, sector_id=visible.id,
                          enabled=True, status='online', last_poll=now())
        offline = Device(name='Hidden radio', ip_address='192.0.2.2', tower_id=shared.id, sector_id=hidden.id,
                         enabled=True, status='online', last_poll=now()-timedelta(hours=1))
        private_device = Device(name='Private radio', ip_address='192.0.2.3', tower_id=private.id)
        db.add_all([assigned, offline, private_device]); db.flush()
        db.add(DeviceAssignment(user_id=tech_id, device_id=assigned.id)); db.commit()
        did, tid = assigned.id, shared.id
    towers = client.get('/api/towers', headers=manager).json()
    assert {t['name'] for t in towers} == {'Assigned', 'Empty'}
    assert all(t['status'] == 'offline' and 'api_username' not in t for t in towers)
    rows = client.get('/api/towers', headers=technician).json()
    assert len(rows) == 1 and rows[0]['id'] == tid and rows[0]['status'] == 'online'
    assert client.get('/api/dashboard', headers=technician).json()['sectors'] == 1
    assert client.get('/api/dashboard', headers=manager).json()['sectors'] == 2
    token = technician['Authorization'].removeprefix('Bearer ')
    assert live_updates.snapshot(token)['rows']['towers'][0]['status'] == 'online'
    with SessionLocal() as db:
        db.get(Device, did).enabled = False
        db.commit()
    assert live_updates.snapshot(token)['rows']['towers'][0]['status'] == 'offline'
    with SessionLocal() as db:
        db.delete(db.get(DeviceAssignment, (tech_id, did))); db.commit()
    restricted = live_updates.snapshot(token)
    assert restricted['rows']['towers'] == [] and restricted['rows']['devices'] == []
    assert restricted['summary']['sectors'] == 0
