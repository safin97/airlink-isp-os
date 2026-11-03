"""Only owners may change profile visibility; no credential readback is granted."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, StrictBool
from sqlalchemy import delete
from sqlalchemy.orm import object_session
from .models import SNMPVisibilityDefault, UserSNMPVisibility, audit
from .db import get_db


def visible(user, db=None):
    if user.role == 'owner':
        return True
    db = db if db is not None else object_session(user)
    if db is not None:
        override = db.get(UserSNMPVisibility, user.id)
        if override is not None:
            return override.enabled
        default = db.get(SNMPVisibilityDefault, 1)
        if default is not None:
            return default.enabled
    # Retain existing Settings grants until the owner sets a visibility preference.
    from . import section_access
    return (user.role == 'manager' or section_access.role_policy(user, db) is not None) and 'settings' in section_access.effective(user, db)


def require(user, db=None):
    if not visible(user, db):
        raise HTTPException(403, 'SNMP profiles are hidden for your account by the owner')


def new_account_default(user):
    db = object_session(user)
    row = db.get(SNMPVisibilityDefault, 1) if db is not None else None
    return row.enabled if row else False


def save(db, user, enabled):
    if enabled is None or user.role == 'owner':
        return
    row = db.get(UserSNMPVisibility, user.id)
    if row is None:
        row = UserSNMPVisibility(user_id=user.id)
        db.add(row)
    row.enabled = enabled


# Import after helpers so request authorization can use them without a cycle.
from .security import owner

router = APIRouter(prefix='/api/snmp-profile-visibility', tags=['SNMP visibility'])


class VisibilityInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    enabled: StrictBool


@router.get('')
def defaults(user=Depends(owner), db=Depends(get_db)):
    row = db.get(SNMPVisibilityDefault, 1)
    return {'enabled': row.enabled if row else False, 'configured': row is not None}


@router.put('')
def set_all(data: VisibilityInput, user=Depends(owner), db=Depends(get_db)):
    row = db.get(SNMPVisibilityDefault, 1)
    if row is None:
        row = SNMPVisibilityDefault(id=1)
        db.add(row)
    row.enabled = data.enabled
    db.execute(delete(UserSNMPVisibility))
    audit(db, user, 'snmp.visibility.all', 'show' if data.enabled else 'hide')
    db.commit()
    return {'enabled': data.enabled, 'configured': True}
