"""Saved API logins for inventory devices, scoped by tower and profile grants."""
import asyncio

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from . import device_login_profiles as profiles, online_device, section_access
from .db import get_db
from .models import DeviceLoginProfile, User, audit, now
from .security import current_user, owner

router = APIRouter(tags=['Towers API'], route_class=online_device.DeviceRoute)
PATH = '/api/towers-api-profiles'


def access(user=Depends(current_user)):
    if user.role not in ('owner', 'manager') and section_access.role_policy(user) is None:
        raise HTTPException(403, 'Tower device login access requires a manager account')
    section_access.require_any(user, ('towers',))
    return user


@router.get(PATH)
def list_profiles(user=Depends(access), db=Depends(get_db)):
    return [profiles.public(db, row, user) for row in db.scalars(
        profiles.visible_query(user).order_by(DeviceLoginProfile.name))]


@router.get(PATH + '/managers')
def managers(user=Depends(owner), db=Depends(get_db)):
    return [{'id': row.id, 'username': row.username} for row in db.scalars(
        select(User).where(User.role == 'manager', User.active.is_(True)).order_by(User.username))]


@router.post(PATH, status_code=201)
def create_profile(data: profiles.ProfileInput, user=Depends(access), db=Depends(get_db)):
    return profiles.save(db, user, data)


@router.put(PATH + '/{profile_id}')
def update_profile(profile_id: str, data: profiles.ProfileInput, user=Depends(access), db=Depends(get_db)):
    return profiles.save(db, user, data, profiles.get_owned_profile(db, user, profile_id))


@router.delete(PATH + '/{profile_id}', status_code=204)
def delete_profile(profile_id: str, user=Depends(access), db=Depends(get_db)):
    db.delete(profiles.get_owned_profile(db, user, profile_id))
    audit(db, user, 'device_login_profile.delete', profile_id)
    db.commit()


class LoginInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    profile_id: str = Field(min_length=1, max_length=36)


@router.post('/api/devices/{device_id}/login')
def login(device_id: str, data: LoginInput, user=Depends(access), db=Depends(get_db)):
    from .api import check_device
    device = check_device(db, user, device_id)
    config, source = profiles.selected_configuration(db, user, data.profile_id)
    # Resolve the address from authorized inventory, never from the request body.
    config = {**config, 'transport': 'web',
              'vendor_hint': 'mikrotik' if device.vendor == 'mikrotik_switch' else device.vendor}
    try:
        result = asyncio.run(online_device.collect(device.ip_address, config))
    except PermissionError:
        raise HTTPException(502, 'Device login rejected. Check the saved username, password and device permissions.') from None
    except TimeoutError:
        raise HTTPException(504, 'Device API connection timed out. Check the service and port.') from None
    except (OSError, ValueError, RuntimeError):
        raise HTTPException(502, 'Device API connection failed. Check the saved connection settings and enable RouterOS REST or airOS web access.') from None
    audit(db, user, 'tower_device.login', device_id)
    db.commit()
    return {**result, 'username': device.name, 'ip_address': device.ip_address,
            'credential_source': source, 'fetched_at': now().isoformat()}
