"""Owner-managed, encrypted device API credentials scoped to towers or SAS4 managers."""
import hashlib
import json
from typing import Literal, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from . import tower_api, sas4, sas4_reports
from .db import get_db
from .models import Tower, CustomerProbeSettings, SAS4UserConnection, audit, now
from .schemas import TowerInput
from .security import owner, cipher

router = APIRouter(prefix='/api/device-api-access', tags=['Device API access'])


class LoginInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    scope: Literal['tower', 'isp_manager']
    target_id: str = Field(min_length=1, max_length=128)
    username: str = Field(min_length=1, max_length=128)
    password: Optional[str] = Field(default=None, max_length=1024)
    protocol: Literal['https', 'http', 'both'] = 'https'
    port: Optional[int] = Field(default=None, ge=1, le=65535)
    verify_tls: bool = True
    enabled: bool = True


def connection_key(connection):
    return hashlib.sha256((sas4.DEFAULT_SERVER + '\0' + connection.username).encode()).hexdigest()


def load_settings(db, user):
    row = db.get(CustomerProbeSettings, user.id)
    return row, json.loads(cipher().decrypt(row.encrypted_settings.encode())) if row else {}


def public_login(config):
    return {'username': config.get('api_username', ''), 'has_password': bool(config.get('api_password')),
            'protocol': config.get('protocol', 'https'), 'port': config.get('port'),
            'verify_tls': config.get('verify_tls', True), 'enabled': config.get('enabled', False)}


def manager_configuration(db, user, manager_id):
    connection = db.get(SAS4UserConnection, user.id)
    if not connection:
        return None
    _, settings = load_settings(db, user)
    return settings.get('manager_device_api', {}).get(connection_key(connection), {}).get(str(manager_id))


@router.get('')
def catalog(user=Depends(owner), db=Depends(get_db)):
    towers = []
    for tower in db.scalars(select(Tower).order_by(Tower.name)):
        towers.append({'id': tower.id, 'name': tower.name, **public_login(tower_api.configuration(db, tower.id))})
    connection = db.get(SAS4UserConnection, user.id)
    _, settings = load_settings(db, user)
    saved = settings.get('manager_device_api', {}).get(connection_key(connection), {}) if connection else {}
    return {'towers': towers, 'isp_managers': [
        {'id': key, 'name': value.get('manager_name', key), **public_login(value)} for key, value in saved.items()]}


@router.put('')
def save(data: LoginInput, user=Depends(owner), db=Depends(get_db)):
    if not data.username.strip():
        raise HTTPException(422, 'Enter a device username')
    if data.scope == 'tower':
        tower = db.get(Tower, data.target_id)
        if tower is None:
            raise HTTPException(404, 'Tower not found')
        tower_api.save(db, tower.id, TowerInput(name=tower.name, api_enabled=data.enabled,
            api_username=data.username, api_password=data.password, api_protocol=data.protocol,
            api_port=data.port, api_verify_tls=data.verify_tls), user)
        config = tower_api.configuration(db, tower.id)
    else:
        connection = db.get(SAS4UserConnection, user.id)
        if not connection:
            raise HTTPException(409, 'Set up SAS4 connection below Settings first')
        try:
            managers = sas4_reports.fetch_managers(connection, cipher().decrypt(connection.encrypted_password.encode()).decode())
        except sas4.SAS4Error as exc:
            raise HTTPException(502, str(exc)) from None
        manager = next((m for m in managers if str(m['id']) == data.target_id), None)
        if manager is None:
            raise HTTPException(404, 'SAS4 manager not found in this connection')
        row, settings = load_settings(db, user)
        assignments = settings.setdefault('manager_device_api', {}).setdefault(connection_key(connection), {})
        old = assignments.get(data.target_id, {})
        if data.username != old.get('api_username') and not data.password:
            raise HTTPException(422, 'Enter a password for the new device username')
        password = data.password or old.get('api_password', '')
        if data.enabled and not password:
            raise HTTPException(422, 'Enter a device password')
        config = {'api_username': data.username, 'api_password': password, 'enabled': data.enabled,
                  'protocol': data.protocol, 'port': data.port, 'verify_tls': data.verify_tls,
                  'manager_name': manager['username']}
        assignments[data.target_id] = config
        if row is None:
            row = CustomerProbeSettings(user_id=user.id)
            db.add(row)
        row.encrypted_settings = cipher().encrypt(json.dumps(settings).encode()).decode()
        row.updated_at = now()
    audit(db, user, 'device_api_access.configure', data.scope + ':' + data.target_id)
    db.commit()
    return public_login(config)
