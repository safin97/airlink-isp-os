"""Write-only, encrypted credentials inherited by devices in a tower."""
import json
from fastapi import HTTPException
from sqlalchemy import select
from .models import TowerAPISettings, Device
from .security import cipher

FIELDS = {'api_enabled', 'api_username', 'api_password', 'api_protocol', 'api_port', 'api_verify_tls'}
DEFAULTS = dict(enabled=False, api_username='', api_password='', protocol='https', port=None, verify_tls=True)
KEYS = dict(api_enabled='enabled', api_username='api_username', api_password='api_password',
            api_protocol='protocol', api_port='port', api_verify_tls='verify_tls')


def configuration(db, tower_id):
    row = db.get(TowerAPISettings, tower_id)
    return {**DEFAULTS, **(json.loads(cipher().decrypt(row.encrypted_credentials.encode())) if row else {})}


def public_settings(db, tower_id, user):
    if user.role != 'owner':
        return {}
    config = configuration(db, tower_id)
    return {**{key: config[value] for key, value in KEYS.items() if key != 'api_password'},
            'has_api_password': bool(config['api_password'])}


def save(db, tower_id, data, user):
    fields = data.model_fields_set & FIELDS
    if not fields:
        return
    if user.role != 'owner':
        raise HTTPException(403, 'Only owner configures tower API credentials')
    old = configuration(db, tower_id)
    config = dict(old)
    for field in fields:
        value = getattr(data, field)
        # A blank password keeps the stored secret. Disabling API stops polling.
        if field == 'api_password' and not value:
            continue
        if value is not None or field == 'api_port':
            config[KEYS[field]] = value
    if config['api_username'] != old['api_username'] and old['api_password'] and not data.api_password:
        raise HTTPException(422, 'Enter a password for the new API username')
    if config['enabled'] and not (config['api_username'].strip() and config['api_password']):
        raise HTTPException(422, 'API username and password are required when API monitoring is enabled')
    if config == old:
        return
    row = db.get(TowerAPISettings, tower_id)
    if row is None:
        row = TowerAPISettings(tower_id=tower_id)
        db.add(row)
    row.encrypted_credentials = cipher().encrypt(json.dumps(config).encode()).decode()
    # New credentials must produce a new poll before old results are displayed.
    for device in db.scalars(select(Device).where(Device.tower_id == tower_id)):
        device.last_poll = None
        device.status = 'unknown'
        device.failures = 0
