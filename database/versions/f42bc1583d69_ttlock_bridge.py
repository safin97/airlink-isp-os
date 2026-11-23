"""Foreground phone bridge for authenticated browser lock management."""
from alembic import op
import sqlalchemy as sa

revision = 'f42bc1583d69'
down_revision = 'e31ab0472c58'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('ttlock_bridges',
        sa.Column('id', sa.String(32), primary_key=True),
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(80), nullable=False),
        sa.Column('token_hash', sa.String(64), nullable=False),
        sa.Column('encrypted_binding', sa.Text(), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('active_job_id', sa.String(32), nullable=True))
    op.create_index('ix_ttlock_bridges_user_id', 'ttlock_bridges', ['user_id'])
    op.create_table('ttlock_bridge_jobs',
        sa.Column('id', sa.String(32), primary_key=True),
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('bridge_id', sa.String(32), sa.ForeignKey('ttlock_bridges.id'), nullable=False),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('encrypted_payload', sa.Text(), nullable=False),
        sa.Column('encrypted_result', sa.Text(), nullable=True),
        sa.Column('claim_hash', sa.String(64), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False))
    op.create_index('ix_ttlock_bridge_jobs_user_id', 'ttlock_bridge_jobs', ['user_id'])


def downgrade():
    op.drop_table('ttlock_bridge_jobs')
    op.drop_table('ttlock_bridges')
