"""Require customer-shared Telegram phone verification before notifications."""
from alembic import op
import sqlalchemy as sa

revision = 'd50eb927318c'
down_revision = 'c49da816207b'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('customer_telegram_links', sa.Column('pending_chat_id', sa.String(30)))
    op.add_column('customer_telegram_links', sa.Column('phone_hash', sa.String(64)))
    op.add_column('customer_telegram_links', sa.Column('phone_verified_at', sa.DateTime(timezone=True)))


def downgrade():
    with op.batch_alter_table('customer_telegram_links') as batch:
        batch.drop_column('phone_verified_at')
        batch.drop_column('phone_hash')
        batch.drop_column('pending_chat_id')
