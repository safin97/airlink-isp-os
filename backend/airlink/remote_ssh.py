"""Owner-only SSH settings using the linked owner's dashboard password."""
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, SecretStr
from typing import Annotated
from .db import get_db
from .models import audit
from .security import verify_password
from .system_terminal import terminal_owner

router = APIRouter(prefix='/api/system/ssh', tags=['SSH remote access'])


class Confirmation(BaseModel):
    model_config = ConfigDict(extra='forbid')
    owner_password: SecretStr = Field(min_length=1, max_length=128)


class Enable(Confirmation):
    sources: list[Annotated[str, Field(max_length=64)]] = Field(min_length=1, max_length=32)


def verify(data, user, db):
    from .api import limited
    limited('ssh-settings:' + user.id, 5)
    # Serialize enablement against a password change for this owner.
    db.refresh(user, with_for_update=True)
    if not verify_password(data.owner_password.get_secret_value(), user.password_hash):
        audit(db, user, 'ssh.authentication_failed')
        db.commit()
        raise HTTPException(403, 'Incorrect owner password')


def call(action, user, db, payload=None):
    from .api import broker
    audit(db, user, 'ssh.' + action + '_requested')
    result = broker('ssh.' + action, payload or {})
    audit(db, user, 'ssh.' + action)
    db.commit()
    return result


@router.get('')
def status(request: Request, user=Depends(terminal_owner)):
    from .api import broker
    result = broker('ssh.status')
    return {**result, 'client_ip': request.client.host if request.client else None}


@router.post('/enable')
def enable(data: Enable, user=Depends(terminal_owner), db=Depends(get_db)):
    verify(data, user, db)
    return call('enable', user, db, {'sources': data.sources,
        'ssh_password': data.owner_password.get_secret_value(),
        'owner_id': user.id, 'owner_username': user.username})


@router.post('/disable')
def disable(data: Confirmation, user=Depends(terminal_owner), db=Depends(get_db)):
    verify(data, user, db)
    return call('disable', user, db)


@router.post('/install', status_code=202)
def install(data: Confirmation, user=Depends(terminal_owner), db=Depends(get_db)):
    verify(data, user, db)
    return call('install', user, db)
