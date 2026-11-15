"""Editable account notification templates by language and recharge method."""
from alembic import op
import sqlalchemy as sa

revision = 'a83bec50641f'
down_revision = 'f72adb49530e'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('recharge_telegram_templates',
        sa.Column('language', sa.String(8), primary_key=True),
        sa.Column('kind', sa.String(20), primary_key=True),
        sa.Column('text', sa.Text(), nullable=False))


def downgrade():
    op.drop_table('recharge_telegram_templates')
