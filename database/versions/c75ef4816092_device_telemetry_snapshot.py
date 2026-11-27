"""Keep last known inventory readings separately from monitoring samples."""
from alembic import op
import sqlalchemy as sa

revision = 'c75ef4816092'
down_revision = 'b64de3705f81'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('device_telemetry_snapshots',
        sa.Column('device_id', sa.String(36), sa.ForeignKey('devices.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('fields', sa.JSON(), nullable=False))


def downgrade():
    op.drop_table('device_telemetry_snapshots')
