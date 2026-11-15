"""Select one owner bot for customer notifications across ISP managers."""
from alembic import op
import sqlalchemy as sa

revision = 'c49da816207b'
down_revision = 'b38cf705196f'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('customer_telegram_sender',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.String(36), sa.ForeignKey('customer_telegram_bots.user_id', ondelete='CASCADE'), nullable=False),
        sa.CheckConstraint('id = 1', name='customer_telegram_single_sender'))
    # Preserve only an unambiguous owner selection; manager bots are never selected.
    op.execute(sa.text("""INSERT INTO customer_telegram_sender (id, user_id)
        SELECT 1, b.user_id FROM customer_telegram_bots b JOIN users u ON u.id = b.user_id
        WHERE u.role = 'owner' AND u.active = true AND
          (SELECT count(*) FROM customer_telegram_bots x JOIN users y ON y.id = x.user_id
           WHERE y.role = 'owner' AND y.active = true) = 1"""))
    op.execute(sa.text("""UPDATE customer_telegram_events SET status = 'cancelled'
        WHERE status = 'pending' AND user_id NOT IN
          (SELECT user_id FROM customer_telegram_sender)"""))


def downgrade():
    op.drop_table('customer_telegram_sender')
