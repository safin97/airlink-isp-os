"""Explicit owner sharing is independent of delegated role edit permissions."""
from sqlalchemy.orm import object_session
from .models import DeyeShare, User


def source(user, db=None):
    if not user.active:
        return None
    from .section_access import _effective
    if user.role == 'owner' or 'deye_management' in _effective(user, db):
        return user
    db = db if db is not None else object_session(user)
    share = db.get(DeyeShare, user.id) if db is not None else None
    owner = db.get(User, share.owner_id) if share is not None else None
    from .section_access import role_policy
    from .models import UserSectionEdits
    policy = role_policy(owner, db) if owner is not None else None
    edits = db.get(UserSectionEdits, owner.id) if owner is not None and db is not None else None
    allowed = owner is not None and (owner.role == 'owner' or
        ('deye_management' in _effective(owner, db) and
         'deye_management' in (policy['edit'] if policy is not None else edits.sections if edits else [])))
    return owner if owner is not None and owner.active and allowed else None


def visible(user, db=None):
    return source(user, db) is not None
