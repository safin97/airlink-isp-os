"""Card profile/pricing configuration, access, and upgrade coverage."""
import importlib.util
from contextlib import contextmanager
from pathlib import Path
import httpx
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect, select
from airlink import sas4
from airlink.db import engine, SessionLocal
from airlink.models import SavedRechargeCard
from test_api import user
from test_sas4 import SETTINGS


def test_profile_and_price_update_is_owner_only_and_keeps_pin(client, owner):
    card = client.post('/api/card-system', headers=owner, json={'pin': 'SECRET-PIN'}).json()
    path = '/api/card-system/' + card['id'] + '/profile'
    _, manager = user(client, owner, 'manager', 'card-price-manager')
    assert client.put(path, headers=manager, json={'profile_id': 3, 'price_iqd': '17500.50'}).status_code == 403
    response = client.put(path, headers=owner, json={'profile_id': 3, 'price_iqd': '17500.50'})
    assert response.status_code == 200
    assert response.json()['profile_id'] == 3 and response.json()['price_iqd'] == '17500.50'
    assert 'SECRET-PIN' not in response.text
    assert client.post('/api/card-system/' + card['id'] + '/pin', headers=owner).json() == {'pin': 'SECRET-PIN'}
    assert client.put(path, headers=owner, json={'profile_id': None, 'price_iqd': '10'}).status_code == 422
    assert client.put(path, headers=owner, json={'profile_id': 0, 'price_iqd': '10'}).status_code == 422


def test_card_profile_list_uses_saved_sas4_connection(client, owner, monkeypatch):
    client.put('/api/integrations/sas4', headers=owner, json=SETTINGS)
    @contextmanager
    def session(connection, password):
        assert connection.username == SETTINGS['username'] and password == SETTINGS['password']
        def handler(request):
            assert request.url.path.endswith('/list/profile/0')
            return httpx.Response(200, json={'status': 200, 'data': [{'id': 3, 'name': '20 Mbps'}, {'id': 4, 'name': '40 Mbps'}]})
        with httpx.Client(transport=httpx.MockTransport(handler)) as remote:
            yield remote, {}
    monkeypatch.setattr(sas4, 'sas4_session', session)
    result = client.get('/api/card-system/profiles', headers=owner)
    assert result.status_code == 200
    assert result.json() == [{'id': 3, 'name': '20 Mbps'}, {'id': 4, 'name': '40 Mbps'}]


def test_card_profile_migration_preserves_existing_inventory(client, owner):
    card = client.post('/api/card-system', headers=owner, json={'label': 'Legacy card', 'pin': 'EXISTING-PIN'}).json()
    path = Path(__file__).resolve().parents[1] / 'database/versions/f86bc5928d03_card_profile_price.py'
    spec = importlib.util.spec_from_file_location('card_profile_migration', path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with engine.begin() as connection:
        migration.op = Operations(MigrationContext.configure(connection))
        migration.downgrade()
        assert 'profile_id' not in {c['name'] for c in inspect(connection).get_columns('saved_recharge_cards')}
        migration.upgrade()
        assert connection.execute(select(SavedRechargeCard.id)).scalar() == card['id']
    with SessionLocal() as db:
        row = db.get(SavedRechargeCard, card['id'])
        assert row.profile_id is None and row.price_iqd is None
    assert client.post('/api/card-system/' + card['id'] + '/pin', headers=owner).json() == {'pin': 'EXISTING-PIN'}
