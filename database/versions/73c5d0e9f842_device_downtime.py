"""Persist the start of a device's observed outage."""
from alembic import op
import sqlalchemy as sa

revision = '73c5d0e9f842'
down_revision = '62b4c9d8e731'
branch_labels = None
depends_on = None


def upgrade():
    # Existing devices have no reliable outage start until a new poll observes it.
    op.add_column('devices', sa.Column('down_since', sa.DateTime(timezone=True), nullable=True))


def downgrade():
    op.drop_column('devices', 'down_since')
