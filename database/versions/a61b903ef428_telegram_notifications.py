"""Add encrypted Telegram settings and durable notification queue."""
from alembic import op
import sqlalchemy as sa
revision = 'a61b903ef428'
down_revision = '95e7f201b064'
branch_labels = None
depends_on = None

def upgrade():
    op.create_table('telegram_settings',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('enabled', sa.Boolean(), nullable=False),
        sa.Column('encrypted_token', sa.Text(), nullable=False),
        sa.Column('chat_id', sa.String(128), nullable=False),
        sa.Column('last_error', sa.String(300)),
        sa.Column('last_sent_at', sa.DateTime(timezone=True)))
    op.create_table('telegram_notifications',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('event_key', sa.String(80), nullable=False, unique=True),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('attempts', sa.Integer(), nullable=False),
        sa.Column('next_attempt', sa.DateTime(timezone=True), nullable=False),
        sa.Column('sent_at', sa.DateTime(timezone=True)))

def downgrade():
    op.drop_table('telegram_notifications')
    op.drop_table('telegram_settings')
