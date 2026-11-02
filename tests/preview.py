"""Local-only browser QA server, ephemeral DB and sessions; not production."""
import os
import sys
import secrets
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
from airlink.models import Role,User,Initialization
from airlink.security import hasher
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
from contextlib import asynccontextmanager, suppress
import asyncio
from monitoring import worker as inventory_worker
inventory_worker.cache = api.cache
original_lifespan = api.app.router.lifespan_context

@asynccontextmanager
async def preview_lifespan(app):
    async with original_lifespan(app):
        task = asyncio.create_task(inventory_worker.main())
        try:
            yield
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

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
api.app.mount('/',StaticFiles(directory=ROOT/'frontend/build/web',html=True),name='dashboard')
uvicorn.run(api.app,host='127.0.0.1',port=18080)
