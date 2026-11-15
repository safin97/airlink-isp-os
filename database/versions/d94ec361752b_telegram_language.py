"""Persist each account's Telegram notification language."""
from alembic import op
import sqlalchemy as sa

revision = 'd94ec361752b'
down_revision = 'c83db250641a'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('telegram_message_templates',
                  sa.Column('language', sa.String(8), nullable=False, server_default='en'))


def downgrade():
    with op.batch_alter_table('telegram_message_templates') as batch:
        batch.drop_column('language')
