"""Encrypted tower device API credentials."""
from alembic import op
import sqlalchemy as sa

revision = 'd52c9b7e14fa'
down_revision = 'c41b8a6d03ef'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('tower_api_settings',
        sa.Column('tower_id', sa.String(36), nullable=False),
        sa.Column('encrypted_credentials', sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(['tower_id'], ['towers.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('tower_id'))


def downgrade():
    op.drop_table('tower_api_settings')
