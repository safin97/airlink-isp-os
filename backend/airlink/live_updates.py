"""Permission-scoped live snapshots and changed-resource frames."""
from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from . import section_access
from .db import SessionLocal
from .security import resolve_user

INTERVAL = 2


def snapshot(token):
    from . import api, access_roles
    with SessionLocal() as db:
        user = resolve_user(token, db)
        def allowed(path):
            try:
                section_access.enforce_request(user, 'GET', '/api/' + path)
                return True
            except HTTPException:
                return False
        rows = {}
        for name, reader in [('towers', api.towers), ('places', api.places),
                             ('sectors', api.sectors), ('devices', api.devices),
                             ('alerts', api.alerts), ('links', api.links)]:
            if allowed(name):
                rows[name] = reader(user=user, db=db)
        if user.role == 'owner':
            rows['users'] = api.users(user=user, db=db)
        if allowed('snmp-profiles'):
            rows['snmp-profiles'] = api.profiles(user=user, db=db)
        if user.role == 'owner' or (section_access.role_policy(user, db) is not None or user.role == 'manager'):
            if allowed('access-roles'):
                rows['access-roles'] = access_roles.groups(user=user, db=db)
        return jsonable_encoder({'user': api.public(user), 'rows': rows,
            'summary': api.summary(db, user) if allowed('dashboard') else {}})


def comparable_summary(value):
    return {k: v for k, v in value.items() if k != 'observed_at'}


def changes(previous, current):
    if previous is None:
        return {'type': 'snapshot', **current}
    result = {'type': 'patch'}
    if previous['user'] != current['user']:
        result['user'] = current['user']
    if comparable_summary(previous['summary']) != comparable_summary(current['summary']):
        result['summary'] = current['summary']
    rows = {key: current['rows'].get(key, []) for key in previous['rows'].keys() | current['rows'].keys()
            if previous['rows'].get(key) != current['rows'].get(key)}
    if rows:
        result['rows'] = rows
    return result if len(result) > 1 else {'type': 'heartbeat'}
