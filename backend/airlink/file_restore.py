"""Owner-only encrypted recovery uploads; bounded chunks fit the controller socket."""
from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, StrictInt
from .db import get_db
from .models import audit
from .security import owner
from .mega_backups import RestoreConfirmation

router = APIRouter(prefix='/api/backups/restore', tags=['Backup file recovery'])


class UploadInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    filename: str = Field(min_length=1, max_length=232)
    size: StrictInt = Field(gt=0, le=20*1024**3)


class UploadToken(BaseModel):
    model_config = ConfigDict(extra='forbid')
    token: str = Field(pattern=r'^[0-9a-f]{48}$')


class UploadChunk(UploadToken):
    offset: StrictInt = Field(ge=0)
    data: str = Field(min_length=1, max_length=43692)


class PrepareUpload(UploadToken):
    password: str = Field(min_length=12, max_length=1024)


def call(action, user, payload=None):
    from .api import broker
    # One recovery coordinator serializes file and MEGA restores.
    return broker('backups.mega.restore.'+action, {**(payload or {}), 'owner_id': user.id})


def record(db, user, action):
    audit(db, user, 'backup.file_restore.'+action)
    db.commit()


@router.get('')
def status(user=Depends(owner)):
    return call('status', user)


@router.post('/uploads', status_code=201)
def start(data: UploadInput, user=Depends(owner), db=Depends(get_db)):
    result = call('upload.start', user, data.model_dump())
    record(db, user, 'upload')
    return result


@router.put('/uploads')
def chunk(data: UploadChunk, user=Depends(owner)):
    return call('upload.chunk', user, data.model_dump())


@router.post('/prepare', status_code=202)
def prepare(data: PrepareUpload, user=Depends(owner), db=Depends(get_db)):
    result = call('upload.prepare', user, data.model_dump())
    record(db, user, 'prepare')
    return result


@router.post('/confirm', status_code=202)
def confirm(data: RestoreConfirmation, user=Depends(owner), db=Depends(get_db)):
    record(db, user, 'request')
    return call('confirm', user, data.model_dump())


@router.post('/cancel')
def cancel(user=Depends(owner), db=Depends(get_db)):
    result = call('cancel', user)
    record(db, user, 'cancel')
    return result
