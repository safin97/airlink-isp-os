"""Places group towers without changing existing inventory."""
from alembic import op
import sqlalchemy as sa

revision = 'e63dab8f25ab'
down_revision = 'd52c9b7e14fa'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('places',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('name', sa.String(120), nullable=False, unique=True))
    op.create_table('tower_places',
        sa.Column('tower_id', sa.String(36), primary_key=True),
        sa.Column('place_id', sa.String(36), nullable=False),
        sa.ForeignKeyConstraint(['tower_id'], ['towers.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['place_id'], ['places.id'], ondelete='RESTRICT'))
    op.create_index('ix_tower_places_place_id', 'tower_places', ['place_id'])


def downgrade():
    op.drop_table('tower_places')
    op.drop_table('places')
