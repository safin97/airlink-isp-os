"""Account-scoped, encrypted reusable device logins."""
from alembic import op
import sqlalchemy as sa
revision = '27a9f1d4c860'
down_revision = '19e8c92d07ba'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('device_login_profiles',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(80), nullable=False),
        sa.Column('encrypted_config', sa.Text(), nullable=False),
        sa.UniqueConstraint('user_id', 'name'))
    op.create_index('ix_device_login_profiles_user_id', 'device_login_profiles', ['user_id'])


def downgrade():
    op.drop_table('device_login_profiles')
