"""Queue phone-based Telegram recharge receipts."""
from alembic import op
import sqlalchemy as sa

revision = 'f72adb49530e'
down_revision = 'e61fca38429d'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('recharge_telegram_settings',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False),
        sa.Column('version', sa.String(36), nullable=False),
        sa.Column('sender_id', sa.String(30), nullable=False),
        sa.Column('sas4_username', sa.String(128), nullable=False),
        sa.Column('language', sa.String(8), nullable=False),
        sa.Column('timezone', sa.String(64), nullable=False),
        sa.CheckConstraint('id = 1'))
    op.create_table('recharge_telegram_events',
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('actor_id', sa.String(36), sa.ForeignKey('users.id', ondelete='SET NULL')),
        sa.Column('customer_id', sa.Integer(), nullable=False),
        sa.Column('version', sa.String(36), nullable=False),
        sa.Column('kind', sa.String(20), nullable=False),
        sa.Column('encrypted_payload', sa.Text(), nullable=False),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('detail', sa.String(300)),
        sa.Column('attempts', sa.Integer(), nullable=False),
        sa.Column('next_attempt', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('sent_at', sa.DateTime(timezone=True)))
    op.create_index('ix_recharge_telegram_events_customer_id', 'recharge_telegram_events', ['customer_id'])


def downgrade():
    op.drop_table('recharge_telegram_events')
    op.drop_table('recharge_telegram_settings')
