"""Add a per-device monitoring connection timeout, preserving existing devices."""
from alembic import op
import sqlalchemy as sa

revision = '62b4c9d8e731'
down_revision = '5f1a6d9c2b40'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('devices', sa.Column('connection_timeout', sa.Integer(),
                                      nullable=False, server_default='2'))


def downgrade():
    op.drop_column('devices', 'connection_timeout')
