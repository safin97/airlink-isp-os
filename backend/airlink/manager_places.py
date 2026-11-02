"""Place assignments include current and future towers without copying memberships."""
from fastapi import HTTPException
from sqlalchemy import select, delete, update, or_
from sqlalchemy.orm import object_session
from .models import ManagerPlace, Place, Tower, TowerPlace


def assigned_places(user_id):
    return select(ManagerPlace.place_id).where(ManagerPlace.user_id == user_id)


def managed_towers(user_id):
    return select(Tower.id).where(or_(
        Tower.manager_id == user_id,
        Tower.id.in_(select(TowerPlace.tower_id).where(
            TowerPlace.place_id.in_(assigned_places(user_id))))))


def public_places(user):
    db = object_session(user)
    return sorted(db.scalars(assigned_places(user.id))) if db and user.role == 'manager' else []


def save(db, user, place_ids):
    if place_ids is None:
        return
    if user.role != 'manager':
        raise HTTPException(422, 'Place assignments apply to manager accounts')
    selected = set(place_ids)
    existing = set(db.scalars(select(Place.id).where(Place.id.in_(selected))))
    if selected != existing:
        raise HTTPException(422, 'One or more selected places no longer exist')
    db.execute(delete(ManagerPlace).where(ManagerPlace.user_id == user.id))
    db.add_all(ManagerPlace(user_id=user.id, place_id=pid) for pid in sorted(selected))
    # Explicit place selection replaces legacy individual tower assignments.
    db.execute(update(Tower).where(Tower.manager_id == user.id).values(manager_id=None))

