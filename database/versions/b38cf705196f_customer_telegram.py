"""Opt-in customer Telegram bot, linking and delivery queue."""
from alembic import op
import sqlalchemy as sa

revision = 'b38cf705196f'
down_revision = 'a27bf694085e'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('customer_telegram_bots',
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('bot_id', sa.String(30), nullable=False, unique=True),
        sa.Column('username', sa.String(128), nullable=False),
        sa.Column('encrypted_token', sa.Text(), nullable=False),
        sa.Column('sas4_username', sa.String(128), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False),
        sa.Column('timezone', sa.String(64), nullable=False),
        sa.Column('offset', sa.Integer(), nullable=False),
        sa.Column('poll_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_error', sa.String(300)))
    op.create_table('customer_telegram_links',
        sa.Column('user_id', sa.String(36), sa.ForeignKey('customer_telegram_bots.user_id', ondelete='CASCADE'), primary_key=True),
        sa.Column('customer_id', sa.Integer(), primary_key=True),
        sa.Column('customer_username', sa.String(128), nullable=False),
        sa.Column('version', sa.String(36), nullable=False),
        sa.Column('language', sa.String(8), nullable=False),
        sa.Column('chat_id', sa.String(30)),
        sa.Column('token_hash', sa.String(64), unique=True),
        sa.Column('token_expires', sa.DateTime(timezone=True)),
        sa.Column('next_check', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_sent_at', sa.DateTime(timezone=True)),
        sa.Column('last_error', sa.String(300)))
    op.create_table('customer_telegram_events',
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('user_id', sa.String(36), sa.ForeignKey('customer_telegram_bots.user_id', ondelete='CASCADE'), nullable=False),
        sa.Column('customer_id', sa.Integer(), nullable=False),
        sa.Column('version', sa.String(36), nullable=False),
        sa.Column('kind', sa.String(20), nullable=False),
        sa.Column('expiration', sa.String(80)),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('attempts', sa.Integer(), nullable=False),
        sa.Column('next_attempt', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('sent_at', sa.DateTime(timezone=True)))
    op.create_index('ix_customer_telegram_events_user_id', 'customer_telegram_events', ['user_id'])


def downgrade():
    op.drop_table('customer_telegram_events')
    op.drop_table('customer_telegram_links')
    op.drop_table('customer_telegram_bots')
