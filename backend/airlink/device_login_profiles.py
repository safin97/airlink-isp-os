"""Reusable device logins: account-isolated and never returned as plaintext."""
import json
from typing import Literal, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from .db import get_db
from .models import DeviceLoginProfile, audit
from .security import cipher
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

    @field_validator('name', 'username')
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError('Enter a name and device username')
        return value.strip()


def get_profile(db, user, profile_id):
    row = db.scalar(select(DeviceLoginProfile).where(
        DeviceLoginProfile.id == profile_id, DeviceLoginProfile.user_id == user.id))
    if row is None:
        raise HTTPException(404, 'Device login profile not found in your account')
    return row


def configuration(row):
    return json.loads(cipher().decrypt(row.encrypted_config.encode()))


def public(row):
    return {'id': row.id, 'name': row.name, **public_login(configuration(row))}


def selected_configuration(db, user, profile_id):
    row = get_profile(db, user, profile_id)
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
    audit(db, user, 'device_login_profile.save', row.id)
    db.commit()
    return public(row)


@router.get('')
def list_profiles(user=Depends(sas4_access), db=Depends(get_db)):
    return [public(row) for row in db.scalars(select(DeviceLoginProfile).where(
        DeviceLoginProfile.user_id == user.id).order_by(DeviceLoginProfile.name))]


@router.post('', status_code=201)
def create_profile(data: ProfileInput, user=Depends(sas4_access), db=Depends(get_db)):
    return save(db, user, data)


@router.put('/{profile_id}')
def update_profile(profile_id: str, data: ProfileInput, user=Depends(sas4_access), db=Depends(get_db)):
    return save(db, user, data, get_profile(db, user, profile_id))


@router.delete('/{profile_id}', status_code=204)
def delete_profile(profile_id: str, user=Depends(sas4_access), db=Depends(get_db)):
    db.delete(get_profile(db, user, profile_id))
    audit(db, user, 'device_login_profile.delete', profile_id)
    db.commit()
