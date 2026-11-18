import importlib.util
from pathlib import Path
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect, select
from airlink.db import engine, SessionLocal
from airlink.models import User, WhatsAppSettings, WhatsAppCustomer, WhatsAppEvent


def test_whatsapp_migration_preserves_accounts_and_matches_models(client, owner):
    path = Path(__file__).resolve().parents[1] / 'database/versions/d16ef2397542_whatsapp_notifications.py'
    spec = importlib.util.spec_from_file_location('whatsapp_migration', path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with SessionLocal() as db:
        user_id = db.scalar(select(User.id))
    with engine.begin() as connection:
        migration.op = Operations(MigrationContext.configure(connection))
        migration.downgrade()
        assert connection.execute(select(User.id)).scalar() == user_id
        migration.upgrade()
        for model in (WhatsAppSettings, WhatsAppCustomer, WhatsAppEvent):
            columns = {c['name'] for c in inspect(connection).get_columns(model.__tablename__)}
            assert columns == {c.name for c in model.__table__.columns}
    with SessionLocal() as db:
        db.add(WhatsAppSettings(id=1, user_id=user_id, sas4_username='owner', encrypted_token='encrypted', config={}))
        db.add(WhatsAppCustomer(user_id=user_id, customer_id=7, customer_username='customer', phone_hash='hash'))
        db.add(WhatsAppEvent(id='event', user_id=user_id, actor_id=user_id, customer_id=7,
                            version='version', customer_version='version', kind='recharge', encrypted_payload='encrypted'))
        db.commit()
        assert db.get(WhatsAppEvent, 'event').status == 'pending'
        assert not db.get(WhatsAppCustomer, (user_id, 7)).enabled
        assert db.get(User, user_id).username == 'owner'
