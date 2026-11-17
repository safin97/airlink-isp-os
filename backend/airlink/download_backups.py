"""Owner-authenticated backup creation and binary download."""
import base64
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from .db import get_db
from .models import audit
from .security import owner

router = APIRouter(prefix='/api/backups/downloads', tags=['Backup downloads'])


class CreateBackup(BaseModel):
    model_config = ConfigDict(extra='forbid')
    password: str = Field(min_length=12, max_length=1024)


def call(action, user, **payload):
    from .api import broker
    return broker('backups.downloads.' + action, {**payload, 'owner_id': user.id})


@router.post('', status_code=202)
def create(data: CreateBackup, user=Depends(owner), db=Depends(get_db)):
    result = call('create', user, password=data.password)
    audit(db, user, 'backup.download.create')
    db.commit()
    return result


@router.get('/{job_id}')
def status(job_id: str, user=Depends(owner)):
    return call('status', user, id=job_id)


@router.get('/{job_id}/file')
def download(job_id: str, user=Depends(owner), db=Depends(get_db)):
    job = call('status', user, id=job_id)
    if job['status'] != 'ready':
        raise HTTPException(409, 'Backup is not ready to download')
    # Read the first block before publishing successful response headers.
    first = base64.b64decode(call('chunk', user, id=job_id, offset=0)['data'], validate=True)
    audit(db, user, 'backup.download.started')
    db.commit()

    def chunks():
        offset = len(first)
        yield first
        while offset < job['size']:
            block = base64.b64decode(call('chunk', user, id=job_id, offset=offset)['data'], validate=True)
            if not block:
                raise RuntimeError('Incomplete backup download')
            offset += len(block)
            yield block

    return StreamingResponse(chunks(), media_type='application/octet-stream', headers={
        'Content-Disposition': 'attachment; filename="' + job['filename'] + '"',
        'Content-Length': str(job['size']), 'Cache-Control': 'no-store',
        'X-Content-Type-Options': 'nosniff', 'X-Backup-SHA256': job['sha256'],
    })
