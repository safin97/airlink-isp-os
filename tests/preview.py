"""Local-only browser QA server, ephemeral DB and sessions; not production."""
import os
import sys
import secrets
import json
from pathlib import Path
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
    CustomerProbeSettings, DeviceLoginProfile, DeviceLoginProfileAccess, now)
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
from contextlib import asynccontextmanager
original_lifespan = api.app.router.lifespan_context

@asynccontextmanager
async def preview_lifespan(app):
    async with original_lifespan(app):
        # Local UI preview must not poll saved inventory or contact device IPs.
        yield

api.app.router.lifespan_context = preview_lifespan
Base.metadata.create_all(engine)
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
    if manager is None:
        manager = User(username='preview-manager', role='manager',
            password_hash=hasher.hash('Preview-Manager-Password-2026!'))
        db.add(manager);db.flush()
    manager_connection = db.get(SAS4UserConnection, manager.id)
    if manager_connection is None:
        manager_connection = SAS4UserConnection(user_id=manager.id,
            username='preview-manager-sas4')
        db.add(manager_connection)
    manager_connection.encrypted_password = cipher().encrypt(b'preview-only').decode()
    connection = db.get(SAS4UserConnection, owner.id)
    if connection is None:
        connection = SAS4UserConnection(user_id=owner.id, username='preview-sas4')
        db.add(connection)
    connection.encrypted_password = cipher().encrypt(b'preview-only').decode()
    settings = db.get(CustomerProbeSettings, owner.id)
    if settings is None:
        settings = CustomerProbeSettings(user_id=owner.id)
        db.add(settings)
    settings.encrypted_settings = cipher().encrypt(json.dumps({
        'enabled': True, 'api_username': 'ubnt', 'api_password': 'preview-only',
        'verify_tls': True, 'allow_http': True, 'try_public_snmp': False,
    }).encode()).decode()
    profile = db.query(DeviceLoginProfile).filter(
        DeviceLoginProfile.user_id == owner.id,
        DeviceLoginProfile.name == 'Demo airMAX login').first()
    if profile is None:
        profile = DeviceLoginProfile(user_id=owner.id, name='Demo airMAX login',
            encrypted_config=cipher().encrypt(json.dumps({
                'api_username': 'ubnt', 'api_password': 'preview-only',
                'protocol': 'both', 'port': None, 'verify_tls': True,
                'enabled': True}).encode()).decode())
        db.add(profile);db.flush()
    if db.get(DeviceLoginProfileAccess, (profile.id, manager.id)) is None:
        db.add(DeviceLoginProfileAccess(profile_id=profile.id,
            manager_id=manager.id))
    db.commit()

# Local-preview-only SAS4 user and airMAX device. No network or real credentials are used.
from airlink import sas4, online_device

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

def preview_enrich(db, user, result):
    rows = []
    for row in result['clients']:
        rows.append({**row, 'telemetry_status': 'available', 'device_reachable': True,
            'detected_vendor': 'ubiquiti_ac', 'vendor_label': 'Ubiquiti airMAX AC',
            'ethernet_links': [{'name': 'eth0', 'speed_mbps': 1000}],
            'signal_dbm': -61, 'ssid': 'AirLink Demo', 'telemetry_source': 'airOS HTTPS'})
    return {**result, 'clients': rows}

async def preview_collect(address, config, transport=None):
    return {'vendor': 'Ubiquiti', 'detected_vendor': 'ubiquiti_ac',
        'device_type': 'Ubiquiti airMAX AC', 'detection_source': 'Device API',
        'wireless': [{'name': 'Wireless', 'ssid': 'AirLink Demo', 'signal_dbm': -61,
                      'tx_rate_mbps': 78, 'rx_rate_mbps': 65}],
        'ethernet': [{'name': 'eth0', 'status': 'link-ok', 'speed_mbps': 1000,
                      'full_duplex': True, 'rx_bps': 24600000, 'tx_bps': 5200000}],
        'pppoe': [], 'pppoe_note': 'PPPoE details are not exposed by the airOS status API.',
        'web_url': 'https://10.123.45.67',
        'groups': {'System': [{'device_model': 'PowerBeam 5AC',
                              'firmware_version': 'WA.v8 preview',
                              'uptime_seconds': 86461}]},
        'registrations': [],
        'settings_note': 'Preview device: airMAX 5AC login and status access succeeded.',
        'connection': {'transport': 'web', 'protocol': 'https', 'verify_tls': True},
        'connection_attempts': [{'connection': 'HTTPS web API', 'status': 'Connected'}]}

sas4.fetch_clients = preview_fetch_clients
sas4.fetch_dashboard = preview_fetch_dashboard
sas4.customer_probe_service.enrich = preview_enrich
online_device.collect = preview_collect
api.app.mount('/',StaticFiles(directory=ROOT/'frontend/build/web',html=True),name='dashboard')
uvicorn.run(api.app,host='127.0.0.1',port=18080)
