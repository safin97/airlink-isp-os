"""Manager assignments by place."""
from alembic import op
import sqlalchemy as sa

revision = 'a85fcd0147cd'
down_revision = 'f74ebc9036bc'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('manager_places',
        sa.Column('user_id', sa.String(36), primary_key=True),
        sa.Column('place_id', sa.String(36), primary_key=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['place_id'], ['places.id'], ondelete='CASCADE'))


def downgrade():
    op.drop_table('manager_places')
