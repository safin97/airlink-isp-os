"""Encrypted per-account Deye Cloud connections."""
from alembic import op
import sqlalchemy as sa

revision = 'e05fd472863c'
down_revision = 'd94ec361752b'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('deye_connections',
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('region', sa.String(8), nullable=False),
        sa.Column('encrypted_credentials', sa.Text(), nullable=False),
        sa.Column('encrypted_token', sa.Text(), nullable=False),
        sa.Column('token_expires', sa.DateTime(timezone=True), nullable=False),
        sa.Column('cache', sa.JSON(), nullable=False))


def downgrade():
    op.drop_table('deye_connections')
