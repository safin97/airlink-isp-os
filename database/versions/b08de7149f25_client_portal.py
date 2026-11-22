"""Separate customer portal settings and revocable sessions."""
from alembic import op
import sqlalchemy as sa
revision = 'b08de7149f25'
down_revision = 'a97cd6038e14'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('client_portal_settings',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('owner_id', sa.String(36), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('sas4_username', sa.String(128), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False),
        sa.Column('subscriber_networks', sa.JSON(), nullable=False),
        sa.Column('version', sa.String(36), nullable=False), sa.CheckConstraint('id = 1'))
    op.create_table('client_portal_sessions',
        sa.Column('digest', sa.String(64), primary_key=True),
        sa.Column('owner_id', sa.String(36), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('config_version', sa.String(36), nullable=False),
        sa.Column('customer_id', sa.Integer(), nullable=False),
        sa.Column('username', sa.String(128), nullable=False),
        sa.Column('source_ip', sa.String(64)), sa.Column('encrypted_token', sa.Text()),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False))
    op.create_index('ix_client_portal_sessions_expires_at', 'client_portal_sessions', ['expires_at'])


def downgrade():
    op.drop_table('client_portal_sessions')
    op.drop_table('client_portal_settings')
