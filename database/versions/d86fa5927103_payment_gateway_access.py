"""Choose which managers may start payments with each shared provider."""
from alembic import op
import sqlalchemy as sa

revision = 'd86fa5927103'
down_revision = 'c75ef4816092'
branch_labels = None
depends_on = None


def upgrade():
    # No row means the legacy all-authorized-users policy. Existing checkout
    # access and in-flight orders remain unchanged until settings are saved.
    op.create_table('payment_gateway_access',
        sa.Column('provider', sa.String(16), sa.ForeignKey('shared_payment_gateways.provider', ondelete='CASCADE'), primary_key=True),
        sa.Column('mode', sa.String(16), nullable=False),
        sa.Column('manager_ids', sa.JSON(), nullable=False),
        sa.CheckConstraint("mode IN ('all', 'selected')"))


def downgrade():
    op.drop_table('payment_gateway_access')
