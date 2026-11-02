"""Consolidate account types into Access Roles without losing existing grants."""
from alembic import op
import sqlalchemy as sa

revision = 'e29df1458b01'
down_revision = 'd18cf0347af0'
branch_labels = None
depends_on = None


def consolidate(connection):
    groups = sa.table('access_roles', sa.column('id', sa.String), sa.column('name', sa.String),
        sa.column('sections', sa.JSON), sa.column('editable_sections', sa.JSON), sa.column('deletable_sections', sa.JSON))
    roles = sa.table('manager_roles', sa.column('id', sa.String), sa.column('name', sa.String), sa.column('access_role_id', sa.String))
    bindings = sa.table('user_manager_roles', sa.column('user_id', sa.String), sa.column('role_id', sa.String))
    direct = sa.table('user_access_roles', sa.column('user_id', sa.String), sa.column('access_role_id', sa.String))
    existing = {row.id: row for row in connection.execute(sa.select(groups))}
    names = {row.name for row in existing.values()}
    assigned = set(connection.execute(sa.select(direct.c.user_id)).scalars())
    for role in connection.execute(sa.select(roles)).all():
        if role.id not in existing:
            source = existing[role.access_role_id]
            name = role.name if role.name not in names else role.name[:48] + ' (' + role.id[:8] + ')'
            connection.execute(groups.insert().values(id=role.id, name=name, sections=source.sections,
                editable_sections=source.editable_sections, deletable_sections=source.deletable_sections))
            names.add(name)
        for user_id in connection.execute(sa.select(bindings.c.user_id).where(bindings.c.role_id == role.id)).scalars():
            if user_id not in assigned:
                connection.execute(direct.insert().values(user_id=user_id, access_role_id=role.id))
                assigned.add(user_id)
    # Retire old permission-management links; all names and grants now exist in access_roles.
    connection.execute(bindings.delete())
    connection.execute(roles.delete())


def upgrade():
    op.create_table('user_access_roles',
        sa.Column('user_id', sa.String(36), primary_key=True),
        sa.Column('access_role_id', sa.String(36), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['access_role_id'], ['access_roles.id'], ondelete='RESTRICT'))
    consolidate(op.get_bind())


def downgrade():
    raise RuntimeError('Direct access-role assignment migration requires a database backup to downgrade')
