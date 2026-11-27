"""Twilio WhatsApp replaces the Meta integration; separate credentials and enrollment."""
from alembic import op
import sqlalchemy as sa

revision = 'b64de3705f81'
down_revision = 'a53cd2694e70'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('twilio_whatsapp_settings',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('sas4_username', sa.String(128), nullable=False),
        sa.Column('encrypted_token', sa.Text(), nullable=False),
        sa.Column('config', sa.JSON(), nullable=False),
        sa.Column('version', sa.String(36), nullable=False),
        sa.Column('verified_at', sa.DateTime(timezone=True)),
        sa.Column('retry_at', sa.DateTime(timezone=True)),
        sa.Column('last_error', sa.String(300)),
        sa.CheckConstraint('id = 1'))
    op.create_table('twilio_whatsapp_customers',
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('customer_id', sa.Integer(), primary_key=True),
        sa.Column('customer_username', sa.String(128), nullable=False),
        sa.Column('phone_hash', sa.String(64), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=False),
        sa.Column('version', sa.String(36), nullable=False),
        sa.Column('consent_at', sa.DateTime(timezone=True)),
        sa.Column('next_check', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_checked', sa.DateTime(timezone=True)),
        sa.Column('last_error', sa.String(300)))
    op.create_index('ix_twilio_whatsapp_customers_next_check', 'twilio_whatsapp_customers', ['next_check'])
    op.create_table('twilio_whatsapp_events',
        sa.Column('id', sa.String(64), primary_key=True),
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('actor_id', sa.String(36), sa.ForeignKey('users.id', ondelete='SET NULL')),
        sa.Column('customer_id', sa.Integer(), nullable=False),
        sa.Column('version', sa.String(36), nullable=False),
        sa.Column('customer_version', sa.String(36), nullable=False),
        sa.Column('kind', sa.String(20), nullable=False),
        sa.Column('encrypted_payload', sa.Text(), nullable=False),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('detail', sa.String(300)),
        sa.Column('attempts', sa.Integer(), nullable=False),
        sa.Column('next_attempt', sa.DateTime(timezone=True), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('accepted_at', sa.DateTime(timezone=True)),
        sa.Column('message_id', sa.String(256)))
    op.create_index('ix_twilio_whatsapp_events_customer_id', 'twilio_whatsapp_events', ['customer_id'])
    op.create_index('ix_twilio_whatsapp_events_status', 'twilio_whatsapp_events', ['status'])

    op.execute(sa.text("UPDATE whatsapp_events SET status = 'cancelled', detail = 'The Meta integration was replaced by Twilio WhatsApp.' WHERE status = 'pending'"))
    op.execute(sa.text("UPDATE whatsapp_customers SET enabled = false"))


def downgrade():
    op.drop_table('twilio_whatsapp_events')
    op.drop_table('twilio_whatsapp_customers')
    op.drop_table('twilio_whatsapp_settings')
