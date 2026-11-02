"""SAS4 connection settings; credentials are encrypted by the application."""
from alembic import op
import sqlalchemy as sa

revision = '7c42a91d0e61'
down_revision = '3c573620b88f'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('sas4_connection',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('server_url', sa.String(500), nullable=False),
        sa.Column('username', sa.String(128), nullable=False),
        sa.Column('encrypted_password', sa.Text(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint('id = 1'), sa.PrimaryKeyConstraint('id'))


def downgrade():
    op.drop_table('sas4_connection')
