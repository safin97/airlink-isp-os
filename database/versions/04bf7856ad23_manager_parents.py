"""Optional manager hierarchy without permission inheritance."""
from alembic import op
import sqlalchemy as sa
revision = '04bf7856ad23'
down_revision = 'f30ea2569c12'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('manager_parents',
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('parent_id', sa.String(36), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.CheckConstraint('user_id != parent_id', name='manager_parent_not_self'))
    op.create_index('ix_manager_parents_parent_id', 'manager_parents', ['parent_id'])


def downgrade():
    op.drop_table('manager_parents')
