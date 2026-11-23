"""Keep one-time TTLock developer application setup separate from account login."""
from alembic import op
import sqlalchemy as sa
revision = 'd20fa9361b47'
down_revision = 'c19ef8250a36'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('ttlock_applications',
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('region', sa.String(8), nullable=False),
        sa.Column('encrypted_credentials', sa.Text(), nullable=False))


def downgrade():
    op.drop_table('ttlock_applications')
