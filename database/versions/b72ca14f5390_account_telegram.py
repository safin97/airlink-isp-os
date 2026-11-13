"""Scope Telegram connections and deliveries to accounts."""
from alembic import op
import sqlalchemy as sa
revision = 'b72ca14f5390'
down_revision = 'a61b903ef428'
branch_labels = None
depends_on = None

def upgrade():
    connection = op.get_bind()
    owner_id = connection.execute(sa.text("SELECT id FROM users WHERE role='owner' ORDER BY created_at, id LIMIT 1")).scalar()
    # Legacy queued messages lack device identity, so they cannot be safely rescoped.
    connection.execute(sa.text('DELETE FROM telegram_notifications'))
    with op.batch_alter_table('telegram_settings') as batch:
        batch.add_column(sa.Column('user_id', sa.String(36)))
    if owner_id:
        connection.execute(sa.text('UPDATE telegram_settings SET user_id=:owner'), {'owner': owner_id})
    else:
        connection.execute(sa.text('DELETE FROM telegram_settings'))
    with op.batch_alter_table('telegram_settings') as batch:
        batch.alter_column('user_id', existing_type=sa.String(36), nullable=False)
        batch.create_unique_constraint('uq_telegram_settings_user', ['user_id'])
        batch.create_foreign_key('fk_telegram_settings_user', 'users', ['user_id'], ['id'], ondelete='CASCADE')
    with op.batch_alter_table('telegram_notifications') as batch:
        batch.add_column(sa.Column('user_id', sa.String(36), nullable=False))
        batch.add_column(sa.Column('device_id', sa.String(36)))
        batch.create_foreign_key('fk_telegram_notification_user', 'users', ['user_id'], ['id'], ondelete='CASCADE')
        batch.create_foreign_key('fk_telegram_notification_device', 'devices', ['device_id'], ['id'], ondelete='CASCADE')

def downgrade():
    raise RuntimeError('Per-account Telegram connections cannot be merged safely into one shared connection')
