"""Delegated reusable roles. Manager inventory scope remains separate."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import object_session
from .db import get_db
from .models import AccessRole, ManagerRole, UserManagerRole, UserAccessRole, BuiltinAccessRole, User, audit
from .schemas import AccessRoleInput, ManagerRoleInput
from .security import delegated_section
from . import section_access

router = APIRouter(prefix='/api')
roles_access = delegated_section('roles')
groups_access = delegated_section('access_roles')


def get(db, model, key):
    value = db.get(model, key)
    if value is None:
        raise HTTPException(404, 'Role or access group not found')
    return value


def public(db, row, user=None):
    result = {c.name: getattr(row, c.name) for c in row.__table__.columns}
    if isinstance(row, ManagerRole):
        result['access_role_name'] = get(db, AccessRole, row.access_role_id).name
    if user is not None:
        policy = row if isinstance(row, AccessRole) else get(db, AccessRole, row.access_role_id)
        result['can_manage'] = grantable(db, user, policy)
    return result


def grantable(db, user, policy):
    if user.role == 'owner':
        return True
    return (set(policy.sections).issubset(section_access.effective(user, db))
            and set(policy.editable_sections).issubset(section_access.editable(user, db))
            and set(policy.deletable_sections).issubset(section_access.deletable(user, db)))


def require_grantable(db, user, policy):
    if not grantable(db, user, policy):
        raise HTTPException(403, 'You can manage only permissions within your own access')


def user_role(user):
    result = {'manager_role_id': None, 'manager_role_name': None, 'access_role_id': None, 'access_role_name': None}
    db = object_session(user)
    direct = db.get(UserAccessRole, user.id) if db and user.role == 'manager' else None
    if direct:
        group = get(db, AccessRole, direct.access_role_id)
        result.update(access_role_id=group.id, access_role_name=group.name)
        return result
    binding = db.get(UserManagerRole, user.id) if db and user.role == 'manager' else None
    if binding:
        role = get(db, ManagerRole, binding.role_id)
        result.update(manager_role_id=role.id, manager_role_name=role.name, access_role_id=role.access_role_id,
                      access_role_name=get(db, AccessRole, role.access_role_id).name)
    builtin = db.get(BuiltinAccessRole, user.role) if db and user.role != 'owner' else None
    if builtin and not builtin.deleted:
        result.update(access_role_name=builtin.name, access_policy_configured=True)
    return result


def assign_input(db, user, data):
    if 'access_role_id' in data.model_fields_set:
        if data.manager_role_id is not None:
            raise HTTPException(422, 'Choose one account type')
        direct = db.get(UserAccessRole, user.id)
        if data.access_role_id is not None:
            if user.role != 'manager':
                raise HTTPException(422, 'Custom access roles apply to manager accounts')
            get(db, AccessRole, data.access_role_id)
            if direct:
                direct.access_role_id = data.access_role_id
            else:
                db.add(UserAccessRole(user_id=user.id, access_role_id=data.access_role_id))
        elif direct:
            db.delete(direct)
        legacy = db.get(UserManagerRole, user.id)
        if legacy:
            db.delete(legacy)
    elif 'manager_role_id' in data.model_fields_set:
        assign(db, user, data.manager_role_id)
    db.flush()
    builtin = db.get(BuiltinAccessRole, user.role)
    if builtin and builtin.deleted and not db.get(UserAccessRole, user.id) and not db.get(UserManagerRole, user.id):
        raise HTTPException(422, 'This account type was deleted. Choose an available access role.')


def assign(db, user, role_id):
    direct = db.get(UserAccessRole, user.id)
    if direct:
        db.delete(direct)
    binding = db.get(UserManagerRole, user.id)
    if role_id is None:
        if binding:
            db.delete(binding)
        return
    if user.role != 'manager':
        raise HTTPException(422, 'Custom roles apply to manager accounts')
    get(db, ManagerRole, role_id)
    if binding:
        binding.role_id = role_id
    else:
        db.add(UserManagerRole(user_id=user.id, role_id=role_id))


@router.get('/access-roles')
def groups(user=Depends(groups_access), db=Depends(get_db)):
    return builtin_types(user, db) + [public(db, row, user) for row in db.scalars(select(AccessRole).order_by(AccessRole.name))]


@router.post('/access-roles', status_code=201)
def add_group(data: AccessRoleInput, user=Depends(groups_access), db=Depends(get_db)):
    require_grantable(db, user, data)
    row = AccessRole(**data.model_dump())
    db.add(row); db.flush()
    audit(db, user, 'access_role.create', row.id)
    db.commit()
    return public(db, row, user)


@router.put('/access-roles/{group_id}')
def edit_group(group_id: str, data: AccessRoleInput, user=Depends(groups_access), db=Depends(get_db)):
    if group_id.startswith('builtin:'):
        return edit_builtin(group_id, data, user, db)
    row = get(db, AccessRole, group_id)
    require_grantable(db, user, row)
    require_grantable(db, user, data)
    for key, value in data.model_dump().items():
        setattr(row, key, value)
    audit(db, user, 'access_role.update', row.id)
    db.commit()
    return public(db, row, user)


@router.delete('/access-roles/{group_id}', status_code=204)
def delete_group(group_id: str, user=Depends(groups_access), db=Depends(get_db)):
    if group_id.startswith('builtin:'):
        return delete_builtin(group_id, user, db)
    row = get(db, AccessRole, group_id)
    require_grantable(db, user, row)
    if db.scalar(select(UserAccessRole.user_id).where(UserAccessRole.access_role_id == row.id).limit(1)):
        raise HTTPException(409, 'This access role is assigned to an account. Reassign the account first.')
    if db.scalar(select(ManagerRole.id).where(ManagerRole.access_role_id == row.id).limit(1)):
        raise HTTPException(409, 'This access role has a legacy assignment. Reassign its accounts first.')
    db.delete(row)
    audit(db, user, 'access_role.delete', group_id)
    db.commit()


@router.get('/roles')
def roles(user=Depends(roles_access), db=Depends(get_db)):
    return [public(db, row, user) for row in db.scalars(select(ManagerRole).order_by(ManagerRole.name))]


@router.post('/roles', status_code=201)
def add_role(data: ManagerRoleInput, user=Depends(roles_access), db=Depends(get_db)):
    require_grantable(db, user, get(db, AccessRole, data.access_role_id))
    row = ManagerRole(**data.model_dump())
    db.add(row); db.flush()
    audit(db, user, 'role.create', row.id)
    db.commit()
    return public(db, row, user)


@router.put('/roles/{role_id}')
def edit_role(role_id: str, data: ManagerRoleInput, user=Depends(roles_access), db=Depends(get_db)):
    row = get(db, ManagerRole, role_id)
    require_grantable(db, user, get(db, AccessRole, row.access_role_id))
    require_grantable(db, user, get(db, AccessRole, data.access_role_id))
    row.name, row.access_role_id = data.name, data.access_role_id
    audit(db, user, 'role.update', row.id)
    db.commit()
    return public(db, row, user)


@router.delete('/roles/{role_id}', status_code=204)
def delete_role(role_id: str, user=Depends(roles_access), db=Depends(get_db)):
    row = get(db, ManagerRole, role_id)
    require_grantable(db, user, get(db, AccessRole, row.access_role_id))
    if db.scalar(select(UserManagerRole.user_id).where(UserManagerRole.role_id == row.id).limit(1)):
        raise HTTPException(409, 'This role is assigned to an account. Reassign the account first.')
    db.delete(row)
    audit(db, user, 'role.delete', role_id)
    db.commit()


@router.get('/roles/access-options')
def role_access_options(user=Depends(roles_access), db=Depends(get_db)):
    # Role editors need selectable names, without access to the Access Roles page.
    return [{'id': row.id, 'name': row.name} for row in
            db.scalars(select(AccessRole).order_by(AccessRole.name)) if grantable(db, user, row)]


def builtin_types(user, db):
    rows = []
    for key, name in [('owner', 'Owner'), ('manager', 'Manager'), ('technician', 'Technician'), ('viewer', 'Viewer')]:
        if key == 'owner' and user.role != 'owner':
            continue
        saved = db.get(BuiltinAccessRole, key) if key != 'owner' else None
        if saved and saved.deleted:
            continue
        read = list(section_access.ALL if key == 'owner' else section_access.OPERATIONAL)
        edit = read if key in ('owner', 'manager') else ['alerts'] if key == 'technician' else []
        delete = read if key in ('owner', 'manager') else []
        rows.append({'id': 'builtin:' + key, 'name': saved.name if saved else name,
                     'account_type': key, 'built_in': True,
                     'sections': saved.sections if saved else read,
                     'editable_sections': saved.editable_sections if saved else edit,
                     'deletable_sections': saved.deletable_sections if saved else delete,
                     'can_manage': key != 'owner' and user.role == 'owner'})
    return rows


def builtin_record(group_id, user, db):
    if user.role != 'owner':
        raise HTTPException(403, 'Only the owner can change system account types')
    key = group_id.removeprefix('builtin:')
    if key not in ('manager', 'technician', 'viewer'):
        raise HTTPException(403, 'Owner access cannot be changed or deleted')
    row = db.get(BuiltinAccessRole, key)
    if row and row.deleted:
        raise HTTPException(404, 'Access role was deleted')
    if row is None:
        source = next(r for r in builtin_types(user, db) if r['account_type'] == key)
        row = BuiltinAccessRole(id=key, **{k: source[k] for k in
            ('name', 'sections', 'editable_sections', 'deletable_sections')})
        db.add(row)
    return row


def edit_builtin(group_id, data, user, db):
    row = builtin_record(group_id, user, db)
    for key, value in data.model_dump().items():
        setattr(row, key, value)
    audit(db, user, 'access_role.update', group_id)
    db.commit()
    return next(r for r in builtin_types(user, db) if r['id'] == group_id)


def delete_builtin(group_id, user, db):
    row = builtin_record(group_id, user, db)
    # Custom-role accounts use the manager security boundary, not the default type.
    used = select(User.id).where(User.role == row.id,
        ~User.id.in_(select(UserAccessRole.user_id)), ~User.id.in_(select(UserManagerRole.user_id)))
    if db.scalar(used.limit(1)):
        raise HTTPException(409, 'This access role is assigned to an account. Reassign the account first.')
    row.deleted = True
    audit(db, user, 'access_role.delete', group_id)
    db.commit()
