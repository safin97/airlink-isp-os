"""Manager hierarchy metadata; links never grant permissions or inventory access."""
from fastapi import HTTPException
from sqlalchemy import select, delete, or_
from sqlalchemy.orm import object_session
from .models import ManagerParent, Role, User


def lock(db):
    # Serialize hierarchy writes on PostgreSQL, including links to previously unlinked users.
    db.execute(select(Role).where(Role.name == 'manager').with_for_update()).all()


def public_parent(user):
    db = object_session(user)
    link = db.get(ManagerParent, user.id) if db else None
    parent = db.get(User, link.parent_id) if link else None
    return {'parent_id': parent.id if parent else None,
            'parent_username': parent.username if parent else None}


def clear(db, user_id):
    db.execute(delete(ManagerParent).where(or_(
        ManagerParent.user_id == user_id, ManagerParent.parent_id == user_id)))


def save(db, user, data):
    if 'parent_id' not in data.model_fields_set:
        return
    parent_id = data.parent_id
    if parent_id is not None:
        parent = db.get(User, parent_id)
        if user.role != 'manager' or not parent or parent.role != 'manager' or not parent.active:
            raise HTTPException(422, 'Choose an active manager as the parent of a manager account')
        visited = {user.id}
        current = parent_id
        while current is not None:
            if current in visited:
                raise HTTPException(422, 'Parent manager cannot be this account or one of its descendants')
            visited.add(current)
            link = db.get(ManagerParent, current)
            current = link.parent_id if link else None
    link = db.get(ManagerParent, user.id)
    if parent_id is None:
        if link:
            db.delete(link)
    elif link:
        link.parent_id = parent_id
    else:
        db.add(ManagerParent(user_id=user.id, parent_id=parent_id))
