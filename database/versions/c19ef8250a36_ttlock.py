"""Owner TTLock connections and durable physical-command deduplication."""
from alembic import op
import sqlalchemy as sa

revision = 'c19ef8250a36'
down_revision = 'b08de7149f25'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('ttlock_connections',
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('region', sa.String(8), nullable=False),
        sa.Column('encrypted_credentials', sa.Text(), nullable=False),
        sa.Column('encrypted_token', sa.Text(), nullable=False),
        sa.Column('token_expires', sa.DateTime(timezone=True), nullable=False))
    op.create_table('ttlock_commands',
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('request_id', sa.String(32), primary_key=True),
        sa.Column('lock_id', sa.BigInteger(), nullable=False),
        sa.Column('action', sa.String(8), nullable=False),
        sa.Column('status', sa.String(20), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False))


def downgrade():
    op.drop_table('ttlock_commands')
    op.drop_table('ttlock_connections')
