import os
import sys
import tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'backend'), str(ROOT / 'os'), str(ROOT)]
# Never inherit an application/production DATABASE_URL implicitly.
os.environ['DATABASE_URL'] = os.environ.get('AIRLINK_TEST_DATABASE_URL') or ('sqlite:///' + tempfile.mktemp(prefix='airlink-test-', suffix='.sqlite'))
os.environ['AIRLINK_JWT_SECRET'] = 'test-only-secret-' * 6
os.environ['AIRLINK_ENCRYPTION_KEY'] = 'gJFepfkBWCaGM4AfJ4vM9MJfW4dT-vWAcFKOg-CyXx8='
os.environ['AIRLINK_BOOTSTRAP_TOKEN'] = 'test-only-bootstrap-' * 3
os.environ['AIRLINK_SECURE_COOKIES'] = 'false'
os.environ['AIRLINK_TESTING'] = 'true'
import pytest
import fakeredis
from fastapi.testclient import TestClient
from airlink import api
from airlink.db import Base, engine, SessionLocal
from airlink.models import Role

PASSWORD = 'AirLink-Testing-Password-428!'

@pytest.fixture()
def client():
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        db.add_all(Role(name=x) for x in ('owner','manager','technician','viewer'))
        db.commit()
    api.cache = fakeredis.FakeRedis(decode_responses=True)
    with TestClient(api.app) as client:
        yield client

@pytest.fixture()
def owner(client):
    r = client.post('/api/setup', json={'username':'owner','password':PASSWORD,'confirm_password':PASSWORD,'token':os.environ['AIRLINK_BOOTSTRAP_TOKEN']})
    assert r.status_code == 201, r.text
    r = client.post('/api/auth/login', json={'username':'owner','password':PASSWORD})
    assert r.status_code == 200, r.text
    return {'Authorization':'Bearer '+r.json()['access_token']}
