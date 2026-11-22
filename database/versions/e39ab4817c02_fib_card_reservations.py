"""Reserve an existing recharge PIN for one bank payment."""
from alembic import op
import sqlalchemy as sa

revision = 'e39ab4817c02'
down_revision = 'd28fa3706b91'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('recharge_card_reservations',
        sa.Column('card_id', sa.String(36), sa.ForeignKey('saved_recharge_cards.id', ondelete='RESTRICT'), primary_key=True),
        sa.Column('payment_id', sa.String(32), sa.ForeignKey('recharge_payments.id', ondelete='RESTRICT'), nullable=False),
        sa.UniqueConstraint('payment_id'))


def downgrade():
    op.drop_table('recharge_card_reservations')
