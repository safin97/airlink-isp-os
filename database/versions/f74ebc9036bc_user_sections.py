"""Owner-controlled manager section access."""
from alembic import op
import sqlalchemy as sa

revision = 'f74ebc9036bc'
down_revision = 'e63dab8f25ab'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('user_section_access',
        sa.Column('user_id', sa.String(36), primary_key=True),
        sa.Column('sections', sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'))


def downgrade():
    op.drop_table('user_section_access')
