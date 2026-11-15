"""Persist observed Deye grid availability estimates per account and station."""
from alembic import op
import sqlalchemy as sa

revision = 'a27bf694085e'
down_revision = 'f16ae583974d'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('deye_grid_history',
        sa.Column('user_id', sa.String(36), sa.ForeignKey('deye_connections.user_id', ondelete='CASCADE'), primary_key=True),
        sa.Column('station_id', sa.String(20), primary_key=True),
        sa.Column('history', sa.JSON(), nullable=False))


def downgrade():
    op.drop_table('deye_grid_history')
