import importlib.util
from pathlib import Path
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import select, inspect
from airlink.db import engine, SessionLocal
from airlink.models import (User, WhatsAppSettings, WhatsAppCustomer, WhatsAppEvent,
    TwilioWhatsAppSettings, TwilioWhatsAppCustomer, TwilioWhatsAppEvent,
    UserSectionAccess, UserSectionEdits, UserSectionDeletes, AccessRole, BuiltinAccessRole)


def test_twilio_whatsapp_migration_preserves_history_without_copying_credentials_or_consent(client, owner):
    spec = importlib.util.spec_from_file_location('twilio_whatsapp_migration', Path(__file__).resolve().parents[1] / 'database/versions/b64de3705f81_twilio_whatsapp.py')
    migration = importlib.util.module_from_spec(spec); spec.loader.exec_module(migration)
    with SessionLocal() as db:
        uid = db.scalar(select(User.id))
        db.add(WhatsAppSettings(id=1, user_id=uid, sas4_username='owner', encrypted_token='old-encrypted-meta-token', config={'recharge': True}))
        db.add(WhatsAppCustomer(user_id=uid, customer_id=7, customer_username='customer', phone_hash='hash', enabled=True))
        for key, state in [('queued', 'pending'), ('history', 'accepted')]:
            db.add(WhatsAppEvent(id=key, user_id=uid, actor_id=uid, customer_id=7, version='old', customer_version='old', kind='recharge', encrypted_payload='old-encrypted-payload', status=state))
        for model in (UserSectionAccess, UserSectionEdits, UserSectionDeletes):
            db.add(model(user_id=uid, sections=['isp_card', 'whatsapp']))
        db.add(AccessRole(id='whatsapp-role', name='WhatsApp role', sections=['whatsapp'], editable_sections=['whatsapp'], deletable_sections=[]))
        db.add(BuiltinAccessRole(id='manager', name='Manager', sections=['whatsapp'], editable_sections=[], deletable_sections=[]))
        db.commit()
    with engine.begin() as connection:
        migration.op = Operations(MigrationContext.configure(connection))
        migration.downgrade()
        migration.upgrade()
        for model in (TwilioWhatsAppSettings, TwilioWhatsAppCustomer, TwilioWhatsAppEvent):
            assert {c['name'] for c in inspect(connection).get_columns(model.__tablename__)} == set(model.__table__.columns.keys())
    with SessionLocal() as db:
        assert db.get(User, uid).username == 'owner'
        assert db.get(WhatsAppSettings, 1).encrypted_token == 'old-encrypted-meta-token'
        assert not db.get(WhatsAppCustomer, (uid, 7)).enabled
        assert db.get(WhatsAppEvent, 'queued').status == 'cancelled'
        assert db.get(WhatsAppEvent, 'history').status == 'accepted'
        for model in (TwilioWhatsAppSettings, TwilioWhatsAppCustomer, TwilioWhatsAppEvent):
            assert db.scalar(select(model)) is None
        for model in (UserSectionAccess, UserSectionEdits, UserSectionDeletes):
            assert db.get(model, uid).sections == ['isp_card', 'whatsapp']
        role = db.get(AccessRole, 'whatsapp-role')
        assert role.sections == ['whatsapp'] and role.editable_sections == ['whatsapp'] and role.deletable_sections == []
        assert db.get(BuiltinAccessRole, 'manager').sections == ['whatsapp']
