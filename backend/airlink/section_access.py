"""Owner-controlled manager sections; roles and inventory scoping still apply."""
from fastapi import HTTPException
from sqlalchemy.orm import object_session
from .models import UserSectionAccess, UserSectionEdits, UserSectionDeletes, UserManagerRole, ManagerRole, AccessRole, UserAccessRole, BuiltinAccessRole

OPERATIONAL = ('dashboard', 'noc', 'towers', 'isp_card', 'monitoring', 'network_map', 'alerts', 'reports')
ASSIGNABLE = (*OPERATIONAL, 'software_updates', 'settings', 'roles', 'access_roles')
ALL = (*ASSIGNABLE, 'managers')
READ_RESOURCES = {
    'dashboard': ('dashboard', 'noc'),
    'towers': ('towers', 'noc', 'network_map', 'monitoring'),
    'places': ('towers',),
    'devices': ('towers', 'noc', 'network_map', 'monitoring'),
    'sectors': ('towers', 'network_map', 'monitoring'),
    'alerts': ('dashboard', 'noc', 'alerts'),
    'links': ('network_map',),
}


def role_policy(user, db=None):
    if user.role == 'owner':
        return None
    db = db if db is not None else object_session(user)
    direct = db.get(UserAccessRole, user.id) if db is not None else None
    if direct:
        group = db.get(AccessRole, direct.access_role_id)
        if group is None:
            return {'read': [], 'edit': [], 'delete': []}
        return {'read': group.sections, 'edit': group.editable_sections, 'delete': group.deletable_sections}
    binding = db.get(UserManagerRole, user.id) if db is not None else None
    if binding is None:
        saved = db.get(BuiltinAccessRole, user.role) if db is not None else None
        if saved is None:
            return None
        if saved.deleted:
            return {'read': [], 'edit': [], 'delete': []}
        return {'read': saved.sections, 'edit': saved.editable_sections, 'delete': saved.deletable_sections}
    role = db.get(ManagerRole, binding.role_id)
    group = db.get(AccessRole, role.access_role_id) if role else None
    if group is None:
        return {'read': [], 'edit': [], 'delete': []}
    return {'read': group.sections, 'edit': group.editable_sections, 'delete': group.deletable_sections}


def effective(user, db=None):
    if user.role == 'owner':
        return list(ALL)
    policy = role_policy(user, db)
    if policy is not None:
        return [key for key in ASSIGNABLE if key in policy['read']]
    if user.role != 'manager':
        return list(OPERATIONAL)
    db = db if db is not None else object_session(user)
    saved = db.get(UserSectionAccess, user.id) if db is not None else None
    # Preserve the operational access of existing managers until the owner changes it.
    return list(OPERATIONAL) if saved is None else [key for key in ASSIGNABLE if key in saved.sections]


def editable(user, db=None):
    visible = effective(user, db)
    policy = role_policy(user, db)
    if policy is not None:
        return [key for key in visible if key in policy['edit']]
    if user.role != 'manager':
        return visible
    db = db if db is not None else object_session(user)
    saved = db.get(UserSectionEdits, user.id) if db is not None else None
    # Preserve existing grants until the owner explicitly sets edit permissions.
    return visible if saved is None else [key for key in visible if key in saved.sections]


def deletable(user, db=None):
    policy = role_policy(user, db)
    if policy is None:
        if user.role == 'manager':
            db = db if db is not None else object_session(user)
            saved = db.get(UserSectionDeletes, user.id) if db is not None else None
            if saved is not None:
                return [key for key in effective(user, db) if key in saved.sections]
            # These newly delegated administrative sections require explicit delete grants.
            return [key for key in editable(user, db) if key not in ('roles', 'access_roles')]
        return editable(user, db)
    return [key for key in effective(user, db) if key in policy['delete']]


def require_any(user, sections, db=None, *, write=False, delete=False):
    if user.role != 'manager' and role_policy(user, db) is None:
        return
    if not set(effective(user, db)).intersection(sections):
        raise HTTPException(403, 'This section is not enabled for your account')
    if delete:
        if not set(deletable(user, db)).intersection(sections):
            raise HTTPException(403, 'Read-only access: deleting is not enabled for this section')
    elif write and not set(editable(user, db)).intersection(sections):
        raise HTTPException(403, 'Read-only access: editing is not enabled for this section')


def enforce_request(user, method, path):
    if user.role != 'manager' and role_policy(user) is None:
        return
    path = path.rstrip('/')
    if path.startswith('/api/auth/'):
        return
    def require(sections):
        return require_any(user, sections, write=method not in ('GET', 'HEAD', 'OPTIONS'), delete=method == 'DELETE')
    if path == '/api/updates' or path.startswith('/api/updates/') or path == '/api/system/restart':
        return require(('software_updates',))
    if path in ('/api/system', '/api/network', '/api/audit', '/api/snmp-profiles') or path.startswith('/api/network/'):
        return require(('settings',))
    if path == '/api/payments/gateways' or path.startswith('/api/payments/gateways/'):
        return require(('settings', 'isp_card'))
    if path == '/api/integrations/sas4':
        return require(('isp_card', 'noc'))
    if path == '/api/integrations/sas4/online-count':
        return require(('noc',))
    if path.startswith(('/api/integrations/sas4/', '/api/payments/')):
        return require(('isp_card',))
    if path.startswith('/api/reports/'):
        return require(('reports',))
    if path.startswith('/api/devices/') and path.endswith('/wireless-clients'):
        return require(('towers', 'noc'))
    if path.startswith('/api/devices/') and path.endswith(('/metrics', '/interfaces')):
        return require(('monitoring',))
    resource = path.removeprefix('/api/').split('/')[0]
    if resource in ('roles', 'access-roles'):
        return require(('roles' if resource == 'roles' else 'access_roles',))
    if method in ('GET', 'HEAD') and resource in READ_RESOURCES:
        return require(READ_RESOURCES[resource])
    if resource in ('towers', 'places', 'devices', 'sectors'):
        return require(('towers',))
    if resource == 'alerts':
        return require(('alerts',))
    # Account administration remains owner-only.
    raise HTTPException(403, 'Owner access required')
