"""Loopback-only dashboard, with opt-in live SAS4 and device monitoring."""
import argparse
import asyncio
import os
import sys
import secrets
import json
from pathlib import Path
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--live', action='store_true', help='Use saved SAS4 connections and monitor saved devices')
parser.add_argument('--port', type=int, default=18080)
args = parser.parse_args()
if not 1024 <= args.port <= 65535:
    parser.error('Choose a local port between 1024 and 65535')
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT/'backend'))
os.environ['DATABASE_URL']='sqlite:////tmp/airlink-browser-qa.sqlite'
os.environ['AIRLINK_JWT_SECRET']=secrets.token_urlsafe(64)
os.environ['AIRLINK_ENCRYPTION_KEY']='gJFepfkBWCaGM4AfJ4vM9MJfW4dT-vWAcFKOg-CyXx8='
os.environ['AIRLINK_SECURE_COOKIES']='false'
from airlink import api
from airlink.db import Base,engine,SessionLocal
from airlink.models import (Role, User, Initialization, SAS4UserConnection,
    now)
from airlink.security import hasher,cipher
from fastapi.staticfiles import StaticFiles
import fakeredis
import uvicorn
from fastapi import HTTPException
sys.path.insert(0, str(ROOT / 'os'))
from updates import update

# Real signed GitHub metadata in the preview, with installation denied server-side.
update.ROOT = ROOT / 'test-results' / 'local-update-preview'
update.CONFIG = ROOT / 'deployment' / 'update-source' / 'update-source.json'
update.KEY = ROOT / 'deployment' / 'update-source' / 'update-public-key.bin'
appliance_broker = api.broker

def preview_broker(action, payload=None):
    if action.startswith('backups.google-drive.'):
        from cloud_backups import service as cloud_backups
        cloud_backups.ROOT = Path('/tmp/airlink-google-drive-preview')
        try:
            return cloud_backups.service.action(action.removeprefix('backups.google-drive.'), payload or {})
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None
    if action == 'system.restart':
        raise HTTPException(409, 'Restart from the dashboard hosted on your AirLink PC. This is a local preview.')
    if action.startswith('updates.'):
        operation = action.split('.', 1)[1]
        if operation not in {'status', 'check'}:
            raise HTTPException(409, 'Install updates from the dashboard hosted on your AirLink PC. This is a local preview.')
        try:
            result = update.action(operation, payload or {})
        except Exception as exc:
            raise HTTPException(409, str(exc)) from exc
        if operation == 'status':
            result.update(install_supported=False, restart_supported=False, preview=True)
        return result
    return appliance_broker(action, payload)

api.broker = preview_broker
api.cache=fakeredis.FakeRedis(decode_responses=True)
from contextlib import asynccontextmanager, suppress

@asynccontextmanager
async def preview_lifespan(app):
    api.settings.validate()
    monitor_task = None
    api.system_stats_service.start()
    if args.live:
        from monitoring import worker
        worker.cache = api.cache
        api.customer_probe_service.start()
        api.customer_collector_service.start()
        monitor_task = asyncio.create_task(worker.main())
    print('AirLink local mode: ' + ('LIVE — real SAS4 and device monitoring' if args.live else 'DEMO — sample SAS4 data'), flush=True)
    try:
        yield
    finally:
        if monitor_task:
            monitor_task.cancel()
            with suppress(asyncio.CancelledError):
                await monitor_task
        api.customer_collector_service.stop()
        api.registration_username_service.stop()
        api.customer_probe_service.stop()
        api.system_stats_service.stop()

api.app.router.lifespan_context = preview_lifespan
Base.metadata.create_all(engine)
# The local preview retains an existing SQLite database between starts.
from sqlalchemy import inspect, text
if 'connection_timeout' not in {column['name'] for column in inspect(engine).get_columns('devices')}:
    with engine.begin() as connection:
        connection.execute(text('ALTER TABLE devices ADD COLUMN connection_timeout INTEGER NOT NULL DEFAULT 2'))
if 'down_since' not in {column['name'] for column in inspect(engine).get_columns('devices')}:
    with engine.begin() as connection:
        connection.execute(text('ALTER TABLE devices ADD COLUMN down_since DATETIME'))
# Keep local accounts aligned with the production consolidation migration.
import importlib.util
migration_spec = importlib.util.spec_from_file_location('preview_direct_access_roles',
    ROOT / 'database/versions/e29df1458b01_direct_access_roles.py')
role_migration = importlib.util.module_from_spec(migration_spec)
migration_spec.loader.exec_module(role_migration)
with engine.begin() as connection:
    role_migration.consolidate(connection)
with SessionLocal() as db:
    if not db.get(Role,'owner'):
        db.add_all(Role(name=x) for x in ['owner','manager','technician','viewer']);db.flush()
        user=User(username='qa-owner',role='owner',password_hash=hasher.hash('Local-browser-QA-2026!'))
        db.add(user);db.flush();db.add(Initialization(id=1,owner_id=user.id));db.commit()
    owner = db.query(User).filter(User.role == 'owner').first()
    manager = db.query(User).filter(User.username == 'preview-manager').first()
    if manager is None and not args.live:
        manager = User(username='preview-manager', role='manager',
            password_hash=hasher.hash('Preview-Manager-Password-2026!'))
        db.add(manager);db.flush()
    manager_connection = db.get(SAS4UserConnection, manager.id) if manager else None
    if manager_connection is None and not args.live:
        manager_connection = SAS4UserConnection(user_id=manager.id,
            username='preview-manager-sas4',
            encrypted_password=cipher().encrypt(b'preview-only').decode())
        db.add(manager_connection)
    connection = db.get(SAS4UserConnection, owner.id)
    if connection is None and not args.live:
        connection = SAS4UserConnection(user_id=owner.id, username='preview-sas4',
            encrypted_password=cipher().encrypt(b'preview-only').decode())
        db.add(connection)
    if args.live:
        # Remove only exact synthetic connection fixtures; retain real profiles and all accounts.
        for saved in db.query(SAS4UserConnection).filter(SAS4UserConnection.username.in_(('preview-sas4', 'preview-manager-sas4'))):
            if cipher().decrypt(saved.encrypted_password.encode()) == b'preview-only':
                db.delete(saved)
    db.commit()

# Local-preview-only SAS4 listing. Explicit device login uses the real API adapters.
from airlink import sas4

DEMO_ONLINE_USER = {
    'id': 5001, 'session_id': 'preview-airmax-5ac', 'username': 'demo-airmax-ac',
    'name': 'Demo airMAX Customer', 'profile': 'Demo 50 Mbps',
    'status': 'active • online', 'online': True, 'ip_address': '10.123.45.67',
    'expiration': '2027-12-31 23:59:59', 'manager': 'preview-manager',
    'mac_address': '02:00:00:00:05:AC', 'nas': 'Preview NAS',
}

def preview_fetch_clients(connection, password, page=1, search='', count=7, transport=None, online=False):
    matches = not search or search.casefold() in DEMO_ONLINE_USER['username'].casefold()
    rows = [dict(DEMO_ONLINE_USER)] if matches else []
    return {'clients': rows, 'total': len(rows), 'page': page, 'per_page': count,
            'last_page': 1, 'fetched_at': now().isoformat()}

def preview_fetch_dashboard(connection, password, transport=None):
    return {'total_users': 1, 'active_users': 1, 'online_users': 1, 'expired_users': 0,
            'about_to_expire': 0, 'balance': '0', 'reward_points': 0, 'warnings': [],
            'fetched_at': now().isoformat()}

def preview_enrich(db, user, result, **kwargs):
    rows = []
    for row in result['clients']:
        rows.append({**row, 'telemetry_status': 'available', 'device_reachable': True,
            'detected_vendor': 'ubiquiti_ac', 'vendor_label': 'Ubiquiti airMAX AC',
            'ethernet_links': [{'name': 'eth0', 'speed_mbps': 1000}],
            'signal_dbm': -61, 'ssid': 'AirLink Demo', 'telemetry_source': 'airOS HTTPS'})
    return {**result, 'clients': rows}

if not args.live:
    sas4.fetch_clients = preview_fetch_clients
    sas4.fetch_dashboard = preview_fetch_dashboard
    sas4.customer_probe_service.enrich = preview_enrich
api.app.mount('/',StaticFiles(directory=ROOT/'frontend/build/web',html=True),name='dashboard')
uvicorn.run(api.app,host='127.0.0.1',port=args.port)
