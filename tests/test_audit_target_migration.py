import importlib.util
from pathlib import Path
import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import inspect, text
from airlink.db import engine


def test_audit_migration_preserves_records_and_rejects_lossy_downgrade(client, owner):
    spec = importlib.util.spec_from_file_location('audit_text_migration',
        Path(__file__).resolve().parents[1] / 'database/versions/95e7f201b064_audit_target_text.py')
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    with engine.begin() as connection:
        migration.op = Operations(MigrationContext.configure(connection))
        before = connection.execute(text('SELECT id, user_id, action, target, created_at FROM audit_logs ORDER BY id')).all()
        migration.downgrade()
        columns = {column['name']: column for column in inspect(connection).get_columns('audit_logs')}
        assert columns['target']['type'].length == 120
        migration.upgrade()
        assert connection.execute(text('SELECT id, user_id, action, target, created_at FROM audit_logs ORDER BY id')).all() == before
        target = 'complete permission details ' * 30
        connection.execute(text('INSERT INTO audit_logs (action, target, created_at) VALUES (:action, :target, CURRENT_TIMESTAMP)'),
                           {'action': 'user.sections', 'target': target})
        assert connection.execute(text("SELECT target FROM audit_logs WHERE action = 'user.sections'")).scalar() == target
        with pytest.raises(RuntimeError, match='exceed 120'):
            migration.downgrade()
