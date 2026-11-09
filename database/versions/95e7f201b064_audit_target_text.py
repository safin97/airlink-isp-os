"""Preserve full audit targets, including all manager permission grants."""
from alembic import op
import sqlalchemy as sa

revision = '95e7f201b064'
down_revision = '84d6e1f0a953'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('audit_logs') as batch:
        batch.alter_column('target', existing_type=sa.String(120), type_=sa.Text(), existing_nullable=True)


def downgrade():
    # Never silently truncate recorded audit details to fit the old schema.
    if op.get_bind().execute(sa.text('SELECT COUNT(*) FROM audit_logs WHERE length(target) > 120')).scalar():
        raise RuntimeError('Cannot narrow audit targets while records exceed 120 characters')
    with op.batch_alter_table('audit_logs') as batch:
        batch.alter_column('target', existing_type=sa.Text(), type_=sa.String(120), existing_nullable=True)
