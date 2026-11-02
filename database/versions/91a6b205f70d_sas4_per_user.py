"""Separate SAS4 credentials for each AirLink account; server endpoint is fixed."""
from alembic import op
import sqlalchemy as sa

revision = '91a6b205f70d'
down_revision = '7c42a91d0e61'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('sas4_user_connections',
        sa.Column('user_id', sa.String(36), nullable=False),
        sa.Column('username', sa.String(128), nullable=False),
        sa.Column('encrypted_password', sa.Text(), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('user_id'))
    # Keep the initial owner's existing credentials only for the same fixed server.
    op.execute("""INSERT INTO sas4_user_connections (user_id, username, encrypted_password, updated_at)
        SELECT i.owner_id, c.username, c.encrypted_password, c.updated_at
        FROM sas4_connection c CROSS JOIN initialization i
        WHERE c.id = 1 AND i.id = 1 AND c.server_url = 'http://airlinkcom.online'""")


def downgrade():
    op.drop_table('sas4_user_connections')
