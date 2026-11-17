"""Owner-only MEGA backup configuration and controls."""
from typing import Optional
from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from .db import get_db
from .models import audit
from .security import owner

router = APIRouter(prefix='/api/backups/mega', tags=['MEGA backups'])


class SettingsInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    email: str = Field(min_length=3, max_length=254)
    account_password: Optional[str] = Field(default=None, max_length=1024)
    backup_password: Optional[str] = Field(default=None, max_length=1024)
    folder: str = Field(default='AirLink Backups', min_length=1, max_length=200)
    automatic_enabled: bool = True
    weekday: int = Field(default=6, ge=0, le=6)
    time: str = Field(default='02:00', pattern=r'^(?:[01][0-9]|2[0-3]):[0-5][0-9]$')
    timezone: str = Field(default='Europe/Zurich', min_length=1, max_length=64)


def call(action, payload=None):
    from .api import broker
    return broker('backups.mega.' + action, payload or {})


def changed(db, user, action):
    audit(db, user, 'backup.mega.' + action)
    db.commit()


@router.get('')
def status(user=Depends(owner)):
    return call('status')


@router.put('')
def configure(data: SettingsInput, user=Depends(owner), db=Depends(get_db)):
    result = call('configure', data.model_dump())
    changed(db, user, 'configure')
    return result


@router.post('/test')
def test_connection(user=Depends(owner), db=Depends(get_db)):
    result = call('test')
    changed(db, user, 'test')
    return result


@router.post('/run')
def run(user=Depends(owner), db=Depends(get_db)):
    result = call('run')
    changed(db, user, 'run')
    return result


@router.post('/disconnect')
def disconnect(user=Depends(owner), db=Depends(get_db)):
    result = call('disconnect')
    changed(db, user, 'disconnect')
    return result


class RestoreInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    filename: str = Field(pattern=r'^AirLink-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{8}\.tar\.airlink$')
    password: str = Field(min_length=12, max_length=1024)


class RestoreConfirmation(BaseModel):
    model_config = ConfigDict(extra='forbid')
    token: str = Field(pattern=r'^[0-9a-f]{48}$')
    confirmation: str = Field(pattern=r'^RESTORE$')


@router.get('/files')
def files(user=Depends(owner)):
    return call('files')


@router.get('/restore')
def restore_status(user=Depends(owner)):
    return call('restore.status', {'owner_id': user.id})


@router.post('/restore/prepare', status_code=202)
def prepare_restore(data: RestoreInput, user=Depends(owner), db=Depends(get_db)):
    result = call('restore.prepare', {**data.model_dump(), 'owner_id': user.id})
    changed(db, user, 'restore.prepare')
    return result


@router.post('/restore/confirm', status_code=202)
def confirm_restore(data: RestoreConfirmation, user=Depends(owner), db=Depends(get_db)):
    # Commit the request audit before the recovery worker may stop the API/database.
    changed(db, user, 'restore.request')
    return call('restore.confirm', {**data.model_dump(), 'owner_id': user.id})


@router.post('/restore/cancel')
def cancel_restore(user=Depends(owner), db=Depends(get_db)):
    result = call('restore.cancel', {'owner_id': user.id})
    changed(db, user, 'restore.cancel')
    return result
