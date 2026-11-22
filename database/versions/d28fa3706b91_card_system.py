"""Saved encrypted recharge card PINs."""
from alembic import op
import sqlalchemy as sa

revision = 'd28fa3706b91'
down_revision = 'd16ef2397542'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('saved_recharge_cards',
        sa.Column('id', sa.String(36), primary_key=True),
        sa.Column('user_id', sa.String(36), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False),
        sa.Column('label', sa.String(120), nullable=False),
        sa.Column('encrypted_pin', sa.Text(), nullable=False),
        sa.Column('pin_digest', sa.String(64), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint('user_id', 'pin_digest', name='uq_saved_card_pin'))
    op.create_index('ix_saved_recharge_cards_user_id', 'saved_recharge_cards', ['user_id'])
    roles = sa.table('builtin_access_roles', sa.column('id', sa.String), sa.column('sections', sa.JSON))
    db = op.get_bind()
    sections = db.execute(sa.select(roles.c.sections).where(roles.c.id == 'owner')).scalar_one_or_none()
    if sections is not None and 'card_system' not in sections:
        db.execute(roles.update().where(roles.c.id == 'owner').values(sections=[*sections, 'card_system']))


def downgrade():
    roles = sa.table('builtin_access_roles', sa.column('id', sa.String), sa.column('sections', sa.JSON))
    db = op.get_bind()
    sections = db.execute(sa.select(roles.c.sections).where(roles.c.id == 'owner')).scalar_one_or_none()
    if sections is not None:
        db.execute(roles.update().where(roles.c.id == 'owner').values(sections=[s for s in sections if s != 'card_system']))
    op.drop_table('saved_recharge_cards')
