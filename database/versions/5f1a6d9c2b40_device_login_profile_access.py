"""Assign saved device login profiles to managers."""
from alembic import op
import sqlalchemy as sa

revision = '5f1a6d9c2b40'
down_revision = '27a9f1d4c860'


def upgrade():
    op.create_table(
        'device_login_profile_access',
        sa.Column('profile_id', sa.String(36), nullable=False),
        sa.Column('manager_id', sa.String(36), nullable=False),
        sa.ForeignKeyConstraint(['profile_id'], ['device_login_profiles.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['manager_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('profile_id', 'manager_id'),
    )
    op.create_index('ix_device_login_profile_access_manager_id',
                    'device_login_profile_access', ['manager_id'])


def downgrade():
    op.drop_index('ix_device_login_profile_access_manager_id',
                  table_name='device_login_profile_access')
    op.drop_table('device_login_profile_access')
