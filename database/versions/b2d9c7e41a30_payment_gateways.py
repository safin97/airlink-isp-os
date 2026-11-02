"""Encrypted merchant configuration and durable payment/recharge records."""
from alembic import op
import sqlalchemy as sa
revision = 'b2d9c7e41a30'
down_revision = '91a6b205f70d'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('payment_gateways',
        sa.Column('user_id', sa.String(36), nullable=False),
        sa.Column('provider', sa.String(16), nullable=False),
        sa.Column('environment', sa.String(16), nullable=False),
        sa.Column('encrypted_credentials', sa.Text(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('user_id', 'provider'))
    op.create_table('recharge_payments',
        sa.Column('id', sa.String(32), nullable=False), sa.Column('user_id', sa.String(36)),
        sa.Column('sas4_user_id', sa.Integer(), nullable=False), sa.Column('sas4_username', sa.String(128), nullable=False),
        sa.Column('provider', sa.String(16), nullable=False), sa.Column('environment', sa.String(16), nullable=False),
        sa.Column('encrypted_credentials', sa.Text(), nullable=False), sa.Column('status', sa.String(32), nullable=False),
        sa.Column('amount', sa.String(40), nullable=False), sa.Column('currency', sa.String(8), nullable=False),
        sa.Column('provider_id', sa.String(128)), sa.Column('quote', sa.JSON(), nullable=False), sa.Column('checkout', sa.JSON()),
        sa.Column('detail', sa.String(500)), sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='SET NULL'), sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('provider', 'environment', 'provider_id', name='uq_recharge_provider_payment'))
    op.create_index('ix_recharge_payments_user_id', 'recharge_payments', ['user_id'])
    op.create_index('ix_recharge_payments_status', 'recharge_payments', ['status'])


def downgrade():
    op.drop_table('recharge_payments')
    op.drop_table('payment_gateways')
