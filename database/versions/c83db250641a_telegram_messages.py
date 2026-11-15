"""Add personal Telegram message templates."""
from alembic import op
import sqlalchemy as sa
revision = 'c83db250641a'
down_revision = 'b72ca14f5390'
branch_labels = None
depends_on = None

def upgrade():
    op.create_table('telegram_message_templates',
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('down_message', sa.Text(), nullable=False),
        sa.Column('recovery_message', sa.Text(), nullable=False))

def downgrade():
    op.drop_table('telegram_message_templates')
