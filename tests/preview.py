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
sys.path.insert(0,str(ROOT/'os'))
# Hold this lock for the whole process so recovery never runs beside another local server.
import fcntl
local_root = ROOT/'.local/mega-backups'
local_root.mkdir(mode=0o700, parents=True, exist_ok=True)
local_process_lock = (local_root/'server.lock').open('a')
try:
    fcntl.flock(local_process_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
except BlockingIOError:
    raise SystemExit('The local AirLink server is already running. Stop it before starting again.')
os.environ['DATABASE_URL']='sqlite:////tmp/airlink-browser-qa.sqlite'
os.environ['AIRLINK_JWT_SECRET']=secrets.token_urlsafe(64)
os.environ.setdefault('AIRLINK_ENCRYPTION_KEY', 'gJFepfkBWCaGM4AfJ4vM9MJfW4dT-vWAcFKOg-CyXx8=')
from airlink.local_restore import LocalRestore
local_restore = LocalRestore(local_root, Path('/tmp/airlink-browser-qa.sqlite'))
os.environ['AIRLINK_ENCRYPTION_KEY'] = local_restore.apply_pending(os.environ['AIRLINK_ENCRYPTION_KEY'])
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
from cloud_backups.download import DownloadService
from airlink.local_backup import archive as local_archive
download_backups = DownloadService(Path('/tmp/airlink-backup-downloads'), archive=local_archive)
from cloud_backups.mega_service import MegaBackupService
if (ROOT/'.tools/rclone').is_file():
    os.environ.setdefault('AIRLINK_RCLONE_BIN', str(ROOT/'.tools/rclone'))
mega_backups = MegaBackupService(local_root, archive=local_archive, enabled=args.live,
                                restore_validate=local_restore.validate, restore_apply=local_restore.stage)

def preview_broker(action, payload=None):
    if action.startswith('vpn.'):
        reason = 'VPN connections run on the installed AirLink Linux PC. This local preview cannot connect a VPN.'
        if action == 'vpn.status':
            return {'supported': False, 'configured': False, 'status': 'unavailable', 'reason': reason}
        raise HTTPException(409, reason)
    if action.startswith('backups.mega.'):
        try:
            return mega_backups.action(action.removeprefix('backups.mega.'), payload or {})
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None
    if action.startswith('backups.downloads.'):
        try:
            return download_backups.action(action.removeprefix('backups.downloads.'), payload or {})
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from None
    if action == 'diagnostics.status':
        from console.driver_health import collect
        sample = api.system_stats_service.read()
        return {'status': 'unavailable', 'problems': [], 'services': {},
                'resources': {'cpu_percent': sample.get('cpu_percent'),
                              'memory_percent': (sample.get('memory') or {}).get('percent'),
                              'storage_percent': (sample.get('storage') or {}).get('percent')},
                'update': {'status': 'Local preview'}, 'recent_errors': [],
                'drivers': collect(sample.get('gpus') or [])}
    if action.startswith('pc-updates.'):
        if action != 'pc-updates.status':
            raise HTTPException(409, 'PC updates run on the installed AirLink Linux PC, not this local preview.')
        return {'supported': False, 'state': {'status': 'unavailable'}, 'plan': None,
                'reboot_required': False,
                'reason': 'PC updates run on the installed AirLink Linux PC. They are unavailable in the local preview.'}
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
    alert_task = None
    customer_messages = None
    whatsapp_messages = None
    pin_payments = None
    api.system_stats_service.start()
    if args.live:
        pin_payments = asyncio.create_task(api.payments.payment_worker(saved_pin_only=True))
        mega_backups.start()
        customer_messages = asyncio.create_task(api.customer_telegram.worker())
        whatsapp_messages = asyncio.create_task(api.whatsapp.worker())
        api.deye_monitor_service.start()
        from monitoring import worker
        worker.cache = api.cache
        api.customer_probe_service.start()
        api.customer_collector_service.start()
        monitor_task = asyncio.create_task(worker.main())
        from monitoring import alerts
        from sqlalchemy import select
        from airlink.models import Device, Metric
        def alert_tick():
            with SessionLocal() as db:
                for device in db.scalars(select(Device).where(Device.enabled.is_(True))):
                    metric = db.scalar(select(Metric).where(Metric.device_id == device.id).order_by(Metric.collected_at.desc()).limit(1))
                    alerts.evaluate(db, device, metric)
                db.commit()
                alerts.telegram.dispatch(db)
        async def local_alerts():
            import logging
            while True:
                try:
                    await asyncio.to_thread(alert_tick)
                except Exception:
                    logging.error('Local alert iteration failed')
                await asyncio.sleep(15)
        alert_task = asyncio.create_task(local_alerts())
    print('AirLink local mode: ' + ('LIVE — real SAS4 and device monitoring' if args.live else 'DEMO — sample SAS4 data'), flush=True)
    try:
        yield
    finally:
        if pin_payments:
            pin_payments.cancel()
            with suppress(asyncio.CancelledError):
                await pin_payments
        mega_backups.stop()
        if whatsapp_messages:
            whatsapp_messages.cancel()
            with suppress(asyncio.CancelledError):
                await whatsapp_messages
        if customer_messages:
            customer_messages.cancel()
            with suppress(asyncio.CancelledError):
                await customer_messages
        if alert_task:
            alert_task.cancel()
            with suppress(asyncio.CancelledError):
                await alert_task
        if monitor_task:
            monitor_task.cancel()
            with suppress(asyncio.CancelledError):
                await monitor_task
        api.deye_monitor_service.stop()
        api.customer_collector_service.stop()
        api.registration_username_service.stop()
        api.customer_probe_service.stop()
        api.system_stats_service.stop()

api.app.router.lifespan_context = preview_lifespan
# Upgrade legacy local Telegram settings before ORM access, preserving a backup.
from sqlalchemy import inspect
if 'telegram_settings' in inspect(engine).get_table_names() and 'user_id' not in {
        col['name'] for col in inspect(engine).get_columns('telegram_settings')}:
    import sqlite3
    import importlib.util
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    backup_path = '/tmp/airlink-before-account-telegram-' + now().strftime('%Y%m%dT%H%M%S') + '.sqlite'
    with sqlite3.connect('/tmp/airlink-browser-qa.sqlite') as source, sqlite3.connect(backup_path) as backup:
        source.backup(backup)
    os.chmod(backup_path, 0o600)
    spec = importlib.util.spec_from_file_location('account_telegram_migration', ROOT / 'database/versions/b72ca14f5390_account_telegram.py')
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
Base.metadata.create_all(engine)
# The local preview retains an existing SQLite database between starts.
from sqlalchemy import inspect, text
if 'profile_id' not in {column['name'] for column in inspect(engine).get_columns('saved_recharge_cards')}:
    with engine.begin() as connection:
        connection.execute(text('ALTER TABLE saved_recharge_cards ADD COLUMN profile_id INTEGER'))
        connection.execute(text('ALTER TABLE saved_recharge_cards ADD COLUMN price_iqd VARCHAR(40)'))
if 'phone_verified_at' not in {column['name'] for column in inspect(engine).get_columns('customer_telegram_links')}:
    import sqlite3
    import importlib.util
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    backup_path = '/tmp/airlink-before-customer-phone-' + now().strftime('%Y%m%dT%H%M%S') + '.sqlite'
    with sqlite3.connect('/tmp/airlink-browser-qa.sqlite') as source, sqlite3.connect(backup_path) as backup:
        source.backup(backup)
    os.chmod(backup_path, 0o600)
    spec = importlib.util.spec_from_file_location('customer_phone_migration', ROOT / 'database/versions/d50eb927318c_customer_telegram_phone.py')
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
if 'dashboard_station' not in {column['name'] for column in inspect(engine).get_columns('deye_connections')}:
    with engine.begin() as connection:
        connection.execute(text('ALTER TABLE deye_connections ADD COLUMN dashboard_station JSON'))
if 'language' not in {column['name'] for column in inspect(engine).get_columns('telegram_message_templates')}:
    with engine.begin() as connection:
        connection.execute(text("ALTER TABLE telegram_message_templates ADD COLUMN language VARCHAR(8) NOT NULL DEFAULT 'en'"))
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
uvicorn.run(api.app,host='127.0.0.1',port=args.port,proxy_headers=False)
