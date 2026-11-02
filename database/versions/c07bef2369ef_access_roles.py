"""Reusable access groups and manager roles."""
from alembic import op
import sqlalchemy as sa

revision = 'c07bef2369ef'
down_revision = 'b96ade1258de'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('access_roles',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('name', sa.String(64), nullable=False, unique=True),
        sa.Column('sections', sa.JSON(), nullable=False),
        sa.Column('editable_sections', sa.JSON(), nullable=False),
        sa.Column('deletable_sections', sa.JSON(), nullable=False))
    op.create_table('manager_roles',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('name', sa.String(64), nullable=False, unique=True),
        sa.Column('access_role_id', sa.String(36), nullable=False),
        sa.ForeignKeyConstraint(['access_role_id'], ['access_roles.id'], ondelete='RESTRICT'))
    op.create_table('user_manager_roles',
        sa.Column('user_id', sa.String(36), primary_key=True),
        sa.Column('role_id', sa.String(36), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['role_id'], ['manager_roles.id'], ondelete='RESTRICT'))


def downgrade():
    op.drop_table('user_manager_roles')
    op.drop_table('manager_roles')
    op.drop_table('access_roles')
