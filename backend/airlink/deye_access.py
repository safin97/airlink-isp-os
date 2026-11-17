"""Explicit owner sharing is independent of delegated role edit permissions."""
from sqlalchemy.orm import object_session
from .models import DeyeShare, User


def source(user, db=None):
    if not user.active:
        return None
    if user.role == 'owner':
        return user
    db = db if db is not None else object_session(user)
    share = db.get(DeyeShare, user.id) if db is not None else None
    owner = db.get(User, share.owner_id) if share is not None else None
    return owner if owner is not None and owner.active and owner.role == 'owner' else None


def visible(user, db=None):
    return source(user, db) is not None
