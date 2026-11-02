"""Editable system account types; deleted types stay removed."""
from alembic import op
import sqlalchemy as sa
revision = 'f30ea2569c12'
down_revision = 'e29df1458b01'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('builtin_access_roles',
        sa.Column('id', sa.String(16), primary_key=True),
        sa.Column('name', sa.String(64), nullable=False),
        sa.Column('sections', sa.JSON(), nullable=False),
        sa.Column('editable_sections', sa.JSON(), nullable=False),
        sa.Column('deletable_sections', sa.JSON(), nullable=False),
        sa.Column('deleted', sa.Boolean(), nullable=False))


def downgrade():
    op.drop_table('builtin_access_roles')
