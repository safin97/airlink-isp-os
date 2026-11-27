"""Owner-only browser terminal. Authentication is checked on every exchange."""
import jwt
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, SecretStr, StrictInt
from .config import settings
from .db import get_db
from .models import audit
from .security import bearer, current_user, verify_password

router = APIRouter(prefix='/api/system/terminal', tags=['System terminal'])


def terminal_owner(user=Depends(current_user)):
    # Root shells are never delegated through settings or access roles.
    if user.role != 'owner':
        raise HTTPException(403, 'Only the system owner can open a system terminal')
    return user


def binding(credentials=Depends(bearer), user=Depends(terminal_owner)):
    claims = jwt.decode(credentials.credentials, settings.secret, algorithms=['HS256'],
                        audience='airlink-dashboard', issuer='airlink')
    return {'owner_id': user.id, 'login_session': claims['sid']}


class Dimensions(BaseModel):
    model_config = ConfigDict(extra='forbid')
    cols: StrictInt = Field(default=100, ge=20, le=300)
    rows: StrictInt = Field(default=30, ge=5, le=120)


class OpenTerminal(Dimensions):
    password: SecretStr = Field(min_length=1, max_length=128)


class SessionInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    session_id: str = Field(pattern=r'^[0-9a-f]{48}$')


class Exchange(SessionInput, Dimensions):
    data: str = Field(default='', max_length=4096)
    sequence: StrictInt = Field(ge=0)
    cursor: StrictInt = Field(ge=0)


def call(action, identity, payload=None):
    from .api import broker
    return broker('terminal.' + action, {**(payload or {}), **identity})


@router.get('')
def status(identity=Depends(binding)):
    return call('status', identity)


@router.post('/open', status_code=201)
def open_terminal(data: OpenTerminal, identity=Depends(binding), user=Depends(terminal_owner), db=Depends(get_db)):
    from .api import limited
    limited('system-terminal:' + user.id, 5)
    if not verify_password(data.password.get_secret_value(), user.password_hash):
        audit(db, user, 'terminal.authentication_failed')
        db.commit()
        raise HTTPException(403, 'Incorrect owner password')
    audit(db, user, 'terminal.open_requested')
    db.commit()
    result = call('open', identity, {'cols': data.cols, 'rows': data.rows})
    audit(db, user, 'terminal.open')
    db.commit()
    return result


@router.post('/exchange')
def exchange(data: Exchange, identity=Depends(binding)):
    return call('exchange', identity, data.model_dump())


@router.post('/close')
def close(data: SessionInput, identity=Depends(binding), user=Depends(terminal_owner), db=Depends(get_db)):
    result = call('close', identity, data.model_dump())
    audit(db, user, 'terminal.close')
    db.commit()
    return result
