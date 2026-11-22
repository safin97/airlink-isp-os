"""Hold SAS4 Radius PINs across all local accounts while a bank payment settles."""
from alembic import op
import sqlalchemy as sa

revision = 'a97cd6038e14'
down_revision = 'f86bc5928d03'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('radius_card_reservations',
        sa.Column('source_key', sa.String(64), primary_key=True),
        sa.Column('payment_id', sa.String(32), sa.ForeignKey('recharge_payments.id', ondelete='RESTRICT'), nullable=False),
        sa.Column('series', sa.String(128), nullable=False),
        sa.Column('remote_card_id', sa.Integer(), nullable=False),
        sa.Column('encrypted_pin', sa.Text(), nullable=False),
        sa.UniqueConstraint('payment_id'))


def downgrade():
    op.drop_table('radius_card_reservations')
