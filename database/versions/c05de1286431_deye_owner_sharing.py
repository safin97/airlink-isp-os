"""Explicit owner-controlled sharing of solar telemetry; existing credentials remain untouched."""
from alembic import op
import sqlalchemy as sa

revision = 'c05de1286431'
down_revision = 'b94cfd617520'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('deye_shares',
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('owner_id', sa.String(36), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False))
    op.create_index('ix_deye_shares_owner_id', 'deye_shares', ['owner_id'])


def downgrade():
    op.drop_table('deye_shares')
