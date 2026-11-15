"""Encrypted owner Telegram user-account sessions for phone lookup."""
from alembic import op
import sqlalchemy as sa

revision = 'e61fca38429d'
down_revision = 'd50eb927318c'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('telegram_accounts',
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('encrypted_state', sa.Text(), nullable=False),
        sa.Column('retry_at', sa.DateTime(timezone=True)))


def downgrade():
    op.drop_table('telegram_accounts')
