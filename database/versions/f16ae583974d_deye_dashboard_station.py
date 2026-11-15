"""Remember the Deye station selected for each account's dashboard."""
from alembic import op
import sqlalchemy as sa

revision = 'f16ae583974d'
down_revision = 'e05fd472863c'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('deye_connections', sa.Column('dashboard_station', sa.JSON(), nullable=True))


def downgrade():
    with op.batch_alter_table('deye_connections') as batch:
        batch.drop_column('dashboard_station')
