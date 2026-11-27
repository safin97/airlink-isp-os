"""Remember the Ethernet speed column's selected port per device."""
from alembic import op
import sqlalchemy as sa

revision = 'e97ab6038214'
down_revision = 'd86fa5927103'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('devices', sa.Column('ethernet_speed_port', sa.String(128), nullable=True))


def downgrade():
    op.drop_column('devices', 'ethernet_speed_port')
