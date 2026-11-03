"""Owner-controlled SNMP profile visibility, separate from role permissions."""
from alembic import op
import sqlalchemy as sa

revision = '19e8c92d07ba'
down_revision = '04bf7856ad23'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('snmp_visibility_default',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('enabled', sa.Boolean(), nullable=False),
        sa.CheckConstraint('id = 1'))
    op.create_table('user_snmp_visibility',
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('enabled', sa.Boolean(), nullable=False))


def downgrade():
    op.drop_table('user_snmp_visibility')
    op.drop_table('snmp_visibility_default')
