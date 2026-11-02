"""Encrypted per-manager customer device polling settings."""
from alembic import op
import sqlalchemy as sa

revision = 'c41b8a6d03ef'
down_revision = 'b2d9c7e41a30'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('customer_probe_settings',
        sa.Column('user_id', sa.String(36), nullable=False),
        sa.Column('encrypted_settings', sa.Text(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('user_id'))


def downgrade():
    op.drop_table('customer_probe_settings')
