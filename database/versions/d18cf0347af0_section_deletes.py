"""Explicit per-account deletion permissions."""
from alembic import op
import sqlalchemy as sa
revision = 'd18cf0347af0'
down_revision = 'c07bef2369ef'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('user_section_deletes',
        sa.Column('user_id', sa.String(36), primary_key=True),
        sa.Column('sections', sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'))


def downgrade():
    op.drop_table('user_section_deletes')
