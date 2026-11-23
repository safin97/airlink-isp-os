"""Durable owner-scoped Bluetooth operations and cloud synchronization."""
from alembic import op
import sqlalchemy as sa

revision = 'e31ab0472c58'
down_revision = 'd20fa9361b47'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('ttlock_mobile_operations',
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('request_id', sa.String(32), primary_key=True),
        sa.Column('lock_id', sa.BigInteger(), nullable=True),
        sa.Column('action', sa.String(24), nullable=False),
        sa.Column('status', sa.String(24), nullable=False),
        sa.Column('encrypted_payload', sa.Text(), nullable=False),
        sa.Column('encrypted_result', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False))


def downgrade():
    op.drop_table('ttlock_mobile_operations')
