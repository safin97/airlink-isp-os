"""Owner-controlled manager sections; roles and inventory scoping still apply."""
from fastapi import HTTPException
from sqlalchemy.orm import object_session
from .models import UserSectionAccess, UserSectionEdits, UserSectionDeletes, UserManagerRole, ManagerRole, AccessRole, UserAccessRole, BuiltinAccessRole

OPERATIONAL = ('dashboard', 'noc', 'towers', 'isp_card', 'monitoring', 'network_map', 'alerts', 'reports')
# New capabilities never inherit legacy operational edit/delete defaults.
ADMINISTRATIVE = ('fib_recharge', 'managers', 'inventory_admin', 'device_login',
                  'towers_api', 'card_system', 'ttlock', 'deye_management',
                  'backups', 'vpn', 'payment_gateways', 'client_portal',
                  'customer_device_access', 'device_api_access', 'telegram_bot',
                  'telegram_account', 'telegram_notifications', 'whatsapp', 'pc_updates', 'snmp_sharing')
ASSIGNABLE = (*OPERATIONAL, 'software_updates', 'settings', 'roles', 'access_roles', 'deye', *ADMINISTRATIVE)
ALL = ASSIGNABLE
OWNER_PAGES = (*OPERATIONAL, 'software_updates', 'settings', 'access_roles', 'deye', 'managers',
               'diagnostics', 'my_account', 'device_login', 'towers_api', 'card_system', 'ttlock')
OWNER_PINNED = ('access_roles', 'my_account')
READ_RESOURCES = {
    'dashboard': ('dashboard', 'noc'),
    'towers': ('towers', 'noc', 'network_map', 'monitoring'),
    'places': ('towers',),
    'devices': ('towers', 'noc', 'network_map', 'monitoring'),
    'sectors': ('towers', 'network_map', 'monitoring'),
    'alerts': ('dashboard', 'noc', 'alerts'),
    'links': ('network_map',),
}


def owner_visibility(user, db=None):
    """Navigation preferences only; owner authorization always remains full."""
    db = db if db is not None else object_session(user)
    saved = db.get(BuiltinAccessRole, 'owner') if db is not None else None
    visible = saved.sections if saved and not saved.deleted else OWNER_PAGES
    return [key for key in OWNER_PAGES if key in visible or key in OWNER_PINNED]


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
    sections = _effective(user, db)
    if user.role == 'owner':
        return sections
    from . import deye_access
    return [key for key in sections if key != 'deye'] + (['deye'] if deye_access.visible(user, db) else [])


def _effective(user, db=None):
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
    visible = [key for key in effective(user, db) if user.role == 'owner' or key != 'deye']
    policy = role_policy(user, db)
    if policy is not None:
        return [key for key in visible if key in policy['edit']]
    if user.role != 'manager':
        return visible
    db = db if db is not None else object_session(user)
    saved = db.get(UserSectionEdits, user.id) if db is not None else None
    # Preserve existing grants until the owner explicitly sets edit permissions.
    return [key for key in visible if key not in ADMINISTRATIVE] if saved is None else [key for key in visible if key in saved.sections]


def deletable(user, db=None):
    policy = role_policy(user, db)
    if policy is None:
        if user.role == 'manager':
            db = db if db is not None else object_session(user)
            saved = db.get(UserSectionDeletes, user.id) if db is not None else None
            if saved is not None:
                return [key for key in effective(user, db) if key != 'deye' and key in saved.sections]
            # These newly delegated administrative sections require explicit delete grants.
            return [key for key in editable(user, db) if key not in ('roles', 'access_roles', *ADMINISTRATIVE)]
        return editable(user, db)
    return [key for key in effective(user, db) if key != 'deye' and key in policy['delete']]


def require_any(user, sections, db=None, *, write=False, delete=False):
    if user.role == 'owner':
        return
    if user.role != 'manager' and role_policy(user, db) is None and not set(sections).intersection(ADMINISTRATIVE):
        return
    if not set(effective(user, db)).intersection(sections):
        raise HTTPException(403, 'This section is not enabled for your account')
    if delete:
        if not set(deletable(user, db)).intersection(sections):
            raise HTTPException(403, 'Read-only access: deleting is not enabled for this section')
    elif write and not set(editable(user, db)).intersection(sections):
        raise HTTPException(403, 'Read-only access: editing is not enabled for this section')


# Exact prefix boundaries prevent look-alike routes from inheriting access.
FEATURE_ROUTES = {
    '/api/integrations/ttlock': 'ttlock', '/api/card-system': 'card_system',
    '/api/vpn': 'vpn', '/api/backups': 'backups',
    '/api/towers-api-profiles': 'towers_api',
    '/api/integrations/sas4/device-login-profiles': 'device_login',
    '/api/integrations/sas4/device-access': 'customer_device_access',
    '/api/device-api-access': 'device_api_access',
    '/api/payments/gateways': 'payment_gateways',
    '/api/client-portal': 'client_portal',
    '/api/integrations/telegram-account': 'telegram_account',
    '/api/integrations/twilio-whatsapp': 'whatsapp',
    '/api/system/pc-updates': 'pc_updates',
    '/api/users': 'managers', '/api/snmp-profile-visibility': 'snmp_sharing',
    '/api/integrations/telegram': 'telegram_notifications',
}


def administrative_feature(path):
    path = path.rstrip('/')
    if path in ('/api/snmp-profiles/discovery-public', '/api/snmp-profiles/discovery-match'):
        return 'inventory_admin'
    for root, feature in FEATURE_ROUTES.items():
        if path == root or path.startswith(root + '/'):
            return feature
    return None


def has_capability(user, feature, db=None, *, write=False, delete=False):
    if user.role == 'owner':
        return True
    permissions = deletable(user, db) if delete else editable(user, db) if write else effective(user, db)
    return feature in permissions


def request_action(method, path, body=None):
    if method in ('GET', 'HEAD', 'OPTIONS'):
        if path.startswith('/api/integrations/ttlock/') and path.endswith('/bluetooth'):
            return 'edit'  # SDK lockData authorizes hardware changes.
        return 'view'
    if method == 'DELETE':
        return 'delete'
    body = body if isinstance(body, dict) else {}
    action = body.get('action') if path in ('/api/card-system/radius/action', '/api/integrations/ttlock/mobile/prepare') else None
    if path == '/api/integrations/ttlock/bridge/jobs' and isinstance(body.get('parameters'), dict):
        action = body['parameters'].get('action')
    if isinstance(action, str) and (action == 'delete' or action.endswith('_delete') or action == 'lock_reset'):
        return 'delete'
    if path.startswith('/api/integrations/ttlock/mobile/') and path.endswith(('/complete', '/sync')):
        return 'view'  # The endpoint rechecks the persisted operation's action.
    if path.startswith('/api/integrations/ttlock/bridge/jobs/') and path.endswith('/claim'):
        return 'view'  # Claim rechecks the queued action before releasing SDK credentials.
    if path.endswith('/delete') or (path.endswith('/disconnect') and not path.startswith('/api/vpn/')):
        return 'delete'
    if path.startswith('/api/card-system/') and path.endswith('/pin'):
        return 'view'
    return 'edit'


def require_feature(user, feature, method='GET', path='', body=None):
    action = request_action(method, path, body)
    require_any(user, (feature,), write=action == 'edit', delete=action == 'delete')


def enforce_request(user, method, path, body=None):
    path = path.rstrip('/')
    feature = administrative_feature(path)
    if feature:
        return require_feature(user, feature, method, path, body)
    if path == '/api/integrations/customer-telegram' and (method not in ('GET', 'HEAD', 'OPTIONS') or has_capability(user, 'telegram_bot')):
        return require_feature(user, 'telegram_bot', method, path, body)
    if path == '/api/integrations/deye' or path.startswith('/api/integrations/deye/'):
        from . import deye_access
        if has_capability(user, 'deye_management'):
            return require_feature(user, 'deye_management', method, path, body)
        if user.role != 'owner' and (method not in ('GET', 'HEAD', 'OPTIONS') or not deye_access.visible(user)):
            raise HTTPException(403, 'Deye Solar configuration and sharing are owner-only; viewing requires owner permission')
        return
    if path.rstrip('/') == '/api/snmp-profiles':
        from . import snmp_visibility
        snmp_visibility.require(user)
        if method in ('GET', 'HEAD', 'OPTIONS'):
            return
    if user.role != 'manager' and role_policy(user) is None:
        return
    path = path.rstrip('/')
    if path in ('/api/integrations/telegram', '/api/integrations/telegram/test', '/api/integrations/telegram/messages'):
        return  # Personal settings; endpoint enforces account type and ownership.
    if path.startswith('/api/auth/'):
        return
    def require(sections):
        return require_any(user, sections, write=method not in ('GET', 'HEAD', 'OPTIONS'), delete=method == 'DELETE')
    if path == '/api/integrations/customer-telegram' or path.startswith('/api/integrations/customer-telegram/'):
        return require_any(user, ('isp_card',), write=method not in ('GET', 'HEAD'))
    if path == '/api/integrations/deye' or path.startswith('/api/integrations/deye/'):
        return require(('deye',))
    if path == '/api/updates' or path.startswith('/api/updates/') or path == '/api/system/restart':
        return require(('software_updates',))
    if path in ('/api/system', '/api/diagnostics', '/api/network', '/api/audit', '/api/snmp-profiles') or path.startswith('/api/network/'):
        return require(('settings',))
    if path == '/api/payments/gateways' or path.startswith('/api/payments/gateways/'):
        return require(('settings', 'isp_card'))
    if path == '/api/integrations/sas4':
        return require(('isp_card', 'noc'))
    if path == '/api/integrations/sas4/online-count':
        return require(('noc',))
    if path == '/api/integrations/sas4/online-device/login' and method == 'POST':
        return require_any(user, ('isp_card',))  # Credentials in body; this operation only reads.
    if path.startswith(('/api/integrations/sas4/', '/api/payments/')):
        return require(('isp_card',))
    if path.startswith('/api/reports/'):
        return require(('reports',))
    if path == '/api/towers-api-profiles' or path.startswith('/api/towers-api-profiles/'):
        return require(('towers',))
    if path.startswith('/api/devices/') and path.endswith('/login') and method == 'POST':
        return require_any(user, ('towers',))  # API login reads device data; no configuration writes.
    if path.startswith('/api/devices/') and path.endswith('/wireless-settings'):
        return require(('towers',) if method != 'GET' else ('towers', 'noc'))
    if path.startswith('/api/devices/') and path.endswith('/wireless-clients'):
        return require(('towers', 'noc'))
    if path.startswith('/api/devices/') and path.endswith('/outages'):
        return require(('towers', 'noc', 'monitoring'))
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
    if resource in ('links', 'discovery') and has_capability(user, 'inventory_admin'):
        return require_feature(user, 'inventory_admin', method, path, body)
    # Unregistered privileged routes remain owner-only.
    raise HTTPException(403, 'Owner access required')
