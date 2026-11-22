"""Assign saved PIN inventory to a service profile and selling price."""
from alembic import op
import sqlalchemy as sa

revision = 'f86bc5928d03'
down_revision = 'e39ab4817c02'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('saved_recharge_cards', sa.Column('profile_id', sa.Integer(), nullable=True))
    op.add_column('saved_recharge_cards', sa.Column('price_iqd', sa.String(40), nullable=True))


def downgrade():
    op.drop_column('saved_recharge_cards', 'price_iqd')
    op.drop_column('saved_recharge_cards', 'profile_id')
