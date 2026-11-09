"""Reusable device logins: account-isolated and never returned as plaintext."""
import json
from typing import Literal, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import delete, or_, select
from .db import get_db
from .models import DeviceLoginProfile, DeviceLoginProfileAccess, User, audit
from .security import cipher, owner
from .sas4 import sas4_access
from .device_access import public_login

router = APIRouter(prefix='/api/integrations/sas4/device-login-profiles', tags=['Device login profiles'])


class ProfileInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    name: str = Field(min_length=1, max_length=80)
    username: str = Field(min_length=1, max_length=128)
    password: Optional[str] = Field(default=None, max_length=1024)
    protocol: Literal['https', 'http', 'both'] = 'both'
    port: Optional[int] = Field(default=None, ge=1, le=65535)
    verify_tls: bool = True
    enabled: bool = True
    manager_ids: Optional[list[str]] = Field(default=None, max_length=500)

    @field_validator('name', 'username')
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError('Enter a name and device username')
        return value.strip()


def get_owned_profile(db, user, profile_id):
    row = db.scalar(select(DeviceLoginProfile).where(
        DeviceLoginProfile.id == profile_id, DeviceLoginProfile.user_id == user.id))
    if row is None:
        raise HTTPException(404, 'Device login profile not found in your account')
    return row


def visible_query(user):
    shared = select(DeviceLoginProfileAccess.profile_id).where(
        DeviceLoginProfileAccess.manager_id == user.id)
    return select(DeviceLoginProfile).where(or_(
        DeviceLoginProfile.user_id == user.id,
        DeviceLoginProfile.id.in_(shared),
    ))


def get_visible_profile(db, user, profile_id):
    row = db.scalar(visible_query(user).where(DeviceLoginProfile.id == profile_id))
    if row is None:
        raise HTTPException(404, 'Device login profile is not available to your account')
    return row


def configuration(row):
    return json.loads(cipher().decrypt(row.encrypted_config.encode()))


def assignments(db, row):
    return [{'id': user.id, 'username': user.username} for user in db.scalars(
        select(User).join(DeviceLoginProfileAccess,
            DeviceLoginProfileAccess.manager_id == User.id).where(
            DeviceLoginProfileAccess.profile_id == row.id).order_by(User.username))]


def public(db, row, user):
    result = {'id': row.id, 'name': row.name, **public_login(configuration(row)),
              'shared': row.user_id != user.id}
    if user.role == 'owner' and row.user_id == user.id:
        result['assigned_managers'] = assignments(db, row)
        result['manager_ids'] = [manager['id'] for manager in result['assigned_managers']]
    return result


def selected_configuration(db, user, profile_id):
    row = get_visible_profile(db, user, profile_id)
    config = configuration(row)
    if not config.get('enabled'):
        raise HTTPException(409, 'This device login profile is disabled')
    return config, row.name


def save(db, user, data, row=None):
    old = configuration(row) if row else {}
    if data.username != old.get('api_username') and not data.password:
        raise HTTPException(422, 'Enter a password for this device username')
    password = data.password or old.get('api_password')
    if not password:
        raise HTTPException(422, 'Enter a device password')
    duplicate = db.scalar(select(DeviceLoginProfile).where(
        DeviceLoginProfile.user_id == user.id, DeviceLoginProfile.name == data.name))
    if duplicate is not None and (row is None or duplicate.id != row.id):
        raise HTTPException(409, 'A device login profile already has this name')
    if row is None:
        row = DeviceLoginProfile(user_id=user.id)
        db.add(row)
    row.name = data.name
    row.encrypted_config = cipher().encrypt(json.dumps({
        'api_username': data.username, 'api_password': password, 'protocol': data.protocol,
        'port': data.port, 'verify_tls': data.verify_tls, 'enabled': data.enabled}).encode()).decode()
    db.flush()
    if data.manager_ids is not None:
        if user.role != 'owner':
            raise HTTPException(403, 'Only the owner can share device login profiles')
        manager_ids = set(data.manager_ids)
        managers = list(db.scalars(select(User).where(
            User.id.in_(manager_ids), User.role == 'manager', User.active.is_(True)))) if manager_ids else []
        if {manager.id for manager in managers} != manager_ids:
            raise HTTPException(422, 'Select active manager accounts only')
        db.execute(delete(DeviceLoginProfileAccess).where(
            DeviceLoginProfileAccess.profile_id == row.id))
        db.add_all(DeviceLoginProfileAccess(profile_id=row.id, manager_id=manager.id)
                   for manager in managers)
    audit(db, user, 'device_login_profile.save', row.id)
    db.commit()
    return public(db, row, user)


@router.get('')
def list_profiles(user=Depends(sas4_access), db=Depends(get_db)):
    return [public(db, row, user) for row in db.scalars(
        visible_query(user).order_by(DeviceLoginProfile.name))]


@router.get('/managers')
def list_managers(user=Depends(owner), db=Depends(get_db)):
    return [{'id': row.id, 'username': row.username} for row in db.scalars(
        select(User).where(User.role == 'manager', User.active.is_(True)).order_by(User.username))]


@router.post('', status_code=201)
def create_profile(data: ProfileInput, user=Depends(sas4_access), db=Depends(get_db)):
    return save(db, user, data)


@router.put('/{profile_id}')
def update_profile(profile_id: str, data: ProfileInput, user=Depends(sas4_access), db=Depends(get_db)):
    return save(db, user, data, get_owned_profile(db, user, profile_id))


@router.delete('/{profile_id}', status_code=204)
def delete_profile(profile_id: str, user=Depends(sas4_access), db=Depends(get_db)):
    db.delete(get_owned_profile(db, user, profile_id))
    audit(db, user, 'device_login_profile.delete', profile_id)
    db.commit()
