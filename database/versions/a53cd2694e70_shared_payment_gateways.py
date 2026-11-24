"""Owner-selected merchant accounts shared by authorized checkout users."""
from alembic import op
import sqlalchemy as sa

revision = 'a53cd2694e70'
down_revision = 'f42bc1583d69'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('shared_payment_gateways',
        sa.Column('provider', sa.String(16), primary_key=True),
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id', ondelete='SET NULL'), nullable=True))
    # Preserve an unambiguous existing owner configuration. Multiple owner bank
    # accounts need an explicit owner save; choosing one could route funds wrong.
    op.execute(sa.text("""
        INSERT INTO shared_payment_gateways (provider, user_id)
        SELECT p.provider, MIN(p.user_id)
        FROM payment_gateways p JOIN users u ON u.id = p.user_id
        WHERE u.role = 'owner' AND u.active = true
        GROUP BY p.provider HAVING COUNT(*) = 1
    """))


def downgrade():
    op.drop_table('shared_payment_gateways')
