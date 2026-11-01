"""Local-only browser QA server, ephemeral DB and sessions; not production."""
import os
import sys
import secrets
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
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
api.cache=fakeredis.FakeRedis(decode_responses=True)
Base.metadata.create_all(engine)
with SessionLocal() as db:
    if not db.get(Role,'owner'):
        db.add_all(Role(name=x) for x in ['owner','manager','technician','viewer']);db.flush()
        user=User(username='qa-owner',role='owner',password_hash=hasher.hash('Local-browser-QA-2026!'))
        db.add(user);db.flush();db.add(Initialization(id=1,owner_id=user.id));db.commit()
api.app.mount('/',StaticFiles(directory=ROOT/'frontend/build/web',html=True),name='dashboard')
uvicorn.run(api.app,host='127.0.0.1',port=18080)
