"""Owner-controlled manager sections; roles and inventory scoping still apply."""
from fastapi import HTTPException
from sqlalchemy.orm import object_session
from .models import UserSectionAccess, UserSectionEdits

OPERATIONAL = ('dashboard', 'noc', 'towers', 'isp_card', 'monitoring', 'network_map', 'alerts', 'reports')
ASSIGNABLE = (*OPERATIONAL, 'software_updates', 'settings')
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


def effective(user, db=None):
    if user.role == 'owner':
        return list(ALL)
    if user.role != 'manager':
        return list(OPERATIONAL)
    db = db if db is not None else object_session(user)
    saved = db.get(UserSectionAccess, user.id) if db is not None else None
    # Preserve the operational access of existing managers until the owner changes it.
    return list(OPERATIONAL) if saved is None else [key for key in ASSIGNABLE if key in saved.sections]


def editable(user, db=None):
    visible = effective(user, db)
    if user.role != 'manager':
        return visible
    db = db if db is not None else object_session(user)
    saved = db.get(UserSectionEdits, user.id) if db is not None else None
    # Preserve existing grants until the owner explicitly sets edit permissions.
    return visible if saved is None else [key for key in visible if key in saved.sections]


def require_any(user, sections, db=None, *, write=False):
    if user.role != 'manager':
        return
    if not set(effective(user, db)).intersection(sections):
        raise HTTPException(403, 'This section is not enabled for your account')
    if write and not set(editable(user, db)).intersection(sections):
        raise HTTPException(403, 'Read-only access: editing is not enabled for this section')


def enforce_request(user, method, path):
    if user.role != 'manager':
        return
    path = path.rstrip('/')
    if path.startswith('/api/auth/'):
        return
    def require(sections):
        return require_any(user, sections, write=method not in ('GET', 'HEAD', 'OPTIONS'))
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
    if path.startswith('/api/devices/') and path.endswith(('/metrics', '/interfaces')):
        return require(('monitoring',))
    resource = path.removeprefix('/api/').split('/')[0]
    if method in ('GET', 'HEAD') and resource in READ_RESOURCES:
        return require(READ_RESOURCES[resource])
    if resource in ('towers', 'places', 'devices', 'sectors'):
        return require(('towers',))
    if resource == 'alerts':
        return require(('alerts',))
    # Account and permission administration remain owner-only.
    raise HTTPException(403, 'Owner access required')
