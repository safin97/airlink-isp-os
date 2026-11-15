"""Optional automatic expiry alerts from the connected owner account."""
from alembic import op
import sqlalchemy as sa

revision = 'b94cfd617520'
down_revision = 'a83bec50641f'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('telegram_expiry_schedule',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('enabled', sa.Boolean(), nullable=False),
        sa.Column('page', sa.Integer(), nullable=False),
        sa.Column('next_check', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_checked', sa.DateTime(timezone=True)),
        sa.Column('last_error', sa.String(300)),
        sa.CheckConstraint('id = 1'))


def downgrade():
    op.drop_table('telegram_expiry_schedule')
