"""Owner-only settings for the appliance's privileged Google Drive backup worker."""
import secrets
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, Field
from typing import Optional
from .db import get_db
from .models import audit
from .security import owner

router = APIRouter(prefix='/api/backups/google-drive', tags=['Google Drive backup'])


class SettingsInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    client_id: str = Field(min_length=10, max_length=300)
    client_secret: Optional[str] = Field(default=None, max_length=4096)
    redirect_uri: str = Field(min_length=10, max_length=2048)
    folder_name: str = Field(default='AirLink Backups', min_length=1, max_length=100)
    backup_password: Optional[str] = Field(default=None, max_length=1024)
    automatic_enabled: bool = True
    weekday: int = Field(default=6, ge=0, le=6)
    time: str = Field(default='02:00', pattern=r'^(?:[01][0-9]|2[0-3]):[0-5][0-9]$')
    timezone: str = Field(default='UTC', min_length=1, max_length=64)


class CompleteInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    state: str = Field(min_length=20, max_length=128)
    code: str = Field(min_length=1, max_length=8192)


def call(action, payload=None):
    from .api import broker
    return broker('backups.google-drive.'+action, payload or {})


def changed(db, user, action):
    audit(db, user, 'backup.google_drive.'+action)
    db.commit()


@router.get('')
def status(user=Depends(owner)):
    return call('status')


@router.put('')
def configure(data: SettingsInput, user=Depends(owner), db=Depends(get_db)):
    result = call('configure', data.model_dump())
    changed(db, user, 'configure')
    return result


@router.post('/authorize')
def authorize(request: Request, user=Depends(owner), db=Depends(get_db)):
    result = call('authorize', {'owner_id': user.id, 'callback': str(request.base_url).rstrip('/')+'/api/backups/google-drive/callback'})
    changed(db, user, 'authorize')
    return result


@router.post('/complete')
def complete(data: CompleteInput, user=Depends(owner), db=Depends(get_db)):
    result = call('complete', {**data.model_dump(), 'owner_id': user.id})
    changed(db, user, 'connect')
    return result


@router.post('/disconnect')
def disconnect(user=Depends(owner), db=Depends(get_db)):
    result = call('disconnect')
    changed(db, user, 'disconnect')
    return result


@router.post('/run')
def run(user=Depends(owner), db=Depends(get_db)):
    result = call('run')
    changed(db, user, 'run')
    return result


@router.get('/callback', response_class=HTMLResponse)
def callback(request: Request):
    # The callback cannot change settings. The owner must complete it through an authenticated POST.
    # Keep OAuth codes out of Uvicorn access logs; the browser still has the original URL.
    request.scope['query_string'] = b''
    nonce = secrets.token_urlsafe(24)
    html = '''<!doctype html><html><head><meta charset="utf-8"><title>AirLink Google Drive</title></head>
<body><p id="result">Returning to AirLink…</p><script nonce="NONCE">
const query = new URLSearchParams(window.location.search);
const result = {type:'airlink-google-drive', code:query.get('code'), state:query.get('state'), error:query.get('error')};
history.replaceState(null, '', window.location.pathname);
if (window.opener) { window.opener.postMessage(result, window.location.origin); window.close(); }
document.getElementById('result').textContent = 'Return to AirLink Settings to finish connecting Google Drive.';
</script></body></html>'''.replace('NONCE', nonce)
    return HTMLResponse(html, headers={'Cache-Control':'no-store', 'Referrer-Policy':'no-referrer',
        'Content-Security-Policy': "default-src 'none'; script-src 'nonce-"+nonce+"'; frame-ancestors 'none'; base-uri 'none'"})
