"""Keep completed device outages after recovery and telemetry retention."""
from alembic import op
import sqlalchemy as sa

revision = '84d6e1f0a953'
down_revision = '73c5d0e9f842'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('device_outages',
        sa.Column('id', sa.String(36), nullable=False),
        sa.Column('device_id', sa.String(36), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('ended_at', sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['device_id'], ['devices.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('device_id', 'started_at'),
        sa.CheckConstraint('ended_at >= started_at'))
    op.create_index('ix_device_outages_device_end', 'device_outages', ['device_id', 'ended_at'])


def downgrade():
    op.drop_index('ix_device_outages_device_end', table_name='device_outages')
    op.drop_table('device_outages')
