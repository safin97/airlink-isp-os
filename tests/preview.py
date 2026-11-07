"""Isolated local review server; persistent local database and no live device actions."""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import re
import secrets
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
LOGIN_FILE = ROOT / 'test-results' / 'local-preview-login.json'
RUNTIME = ROOT / 'test-results' / 'local-preview'


def local_request(method: str, path: str) -> bool:
    """Permit authentication and editing the isolated local database only."""
    if not path.startswith('/api/'):
        return method in {'GET', 'HEAD'}
    if method == 'GET' and path in {
        '/api/health', '/api/setup/status', '/api/auth/me', '/api/dashboard',
        '/api/users', '/api/places', '/api/towers', '/api/sectors', '/api/devices',
        '/api/alerts', '/api/links', '/api/snmp-profiles', '/api/access-roles',
        '/api/roles', '/api/roles/access-options', '/api/audit',
        '/api/reports/availability.csv', '/api/system', '/api/network',
        '/api/updates', '/api/integrations/sas4',
        '/api/integrations/sas4/device-access', '/api/payments/gateways',
        '/api/integrations/sas4/device-login-profiles', '/api/device-api-access',
        '/api/snmp-profile-visibility',
    }:
        return True
    if method == 'POST' and path in {
        '/api/auth/login', '/api/auth/refresh', '/api/auth/logout',
        '/api/updates/check',
        # Device-form presets create/reuse encrypted local records; no scan runs.
        '/api/snmp-profiles/discovery-public',
    }:
        return True
    if method == 'PUT' and path == '/api/auth/password':
        return True
    resources = '(users|places|towers|sectors|devices|links|snmp-profiles|access-roles|roles|integrations/sas4/device-login-profiles)'
    if method == 'POST' and re.fullmatch('/api/' + resources, path):
        return True
    if method in {'PUT', 'DELETE'} and re.fullmatch('/api/' + resources + '/[^/]+', path):
        return True
    if method == 'PUT' and re.fullmatch(r'/api/users/[^/]+/(sections|devices/[^/]+)', path):
        return True
    if method == 'POST' and re.fullmatch(r'/api/users/[^/]+/disable', path):
        return True
    if method == 'POST' and re.fullmatch(r'/api/alerts/[^/]+/acknowledge', path):
        return True
    if method == 'GET' and re.fullmatch(r'/api/devices/[^/]+/(metrics|interfaces)', path):
        return True
    if method == 'PUT' and re.fullmatch(r'/api/devices/[^/]+/snmp-profile', path):
        return True
    if method == 'PUT' and path == '/api/snmp-profile-visibility':
        return True
    return False


def write_private_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as file:
        json.dump(data, file)
        file.write('\n')
        temporary = Path(file.name)
    os.chmod(temporary, 0o600)
    temporary.replace(path)


def preview_state(runtime: Path, login_file: Path) -> dict:
    from cryptography.fernet import Fernet
    runtime.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(runtime, 0o700)
    state_file = runtime / 'secrets.json'
    if state_file.exists():
        return json.loads(state_file.read_text())
    if (runtime / 'preview.sqlite').exists():
        raise RuntimeError('Preview keys are missing. Restore secrets.json before reusing this preview database.')
    previous = json.loads(login_file.read_text()) if login_file.exists() else {}
    password = previous.get('password') if previous.get('username') == 'preview-owner' else None
    state = {
        'username': 'preview-owner',
        'password': password if isinstance(password, str) and len(password) >= 14 else secrets.token_urlsafe(24),
        'jwt_secret': secrets.token_urlsafe(64),
        'encryption_key': Fernet.generate_key().decode(),
        'bootstrap_token': secrets.token_urlsafe(48),
    }
    write_private_json(state_file, state)
    return state


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='127.0.0.1', choices=['127.0.0.1', 'localhost', '::1'])
    parser.add_argument('--port', type=int, default=18080)
    parser.add_argument('--strictPort', action='store_true')
    parser.add_argument('--check', action='store_true', help='Check local login and isolation without starting a server')
    args = parser.parse_args()
    web_root = ROOT / 'frontend' / 'build' / 'web'
    if not (web_root / 'index.html').is_file():
        parser.error('Build the Flutter web dashboard first; see docs/LOCAL-PREVIEW.md.')
    if not 1 <= args.port <= 65535:
        parser.error('Port must be between 1 and 65535.')

    runtime = RUNTIME
    state = preview_state(runtime, LOGIN_FILE)
    # Override inherited production configuration before importing the app.
    os.environ.update({
        'DATABASE_URL': 'sqlite:///' + str(runtime / 'preview.sqlite'),
        'REDIS_URL': 'redis://127.0.0.1:6379/15',
        'AIRLINK_JWT_SECRET': state['jwt_secret'],
        'AIRLINK_ENCRYPTION_KEY': state['encryption_key'],
        'AIRLINK_BOOTSTRAP_TOKEN': state['bootstrap_token'],
        'AIRLINK_SECURE_COOKIES': 'false',
        'AIRLINK_TESTING': 'true',
        'AIRLINK_BROKER_SOCKET': str(runtime / 'disabled-control.sock'),
    })
    sys.path[:0] = [str(ROOT / 'backend'), str(ROOT / 'os'), str(ROOT)]
    import fakeredis
    import uvicorn
    from fastapi import HTTPException
    from fastapi.responses import JSONResponse
    from fastapi.staticfiles import StaticFiles
    from airlink import api
    from airlink.db import Base, engine, SessionLocal
    from airlink.models import Role, User, Initialization
    from airlink.security import hasher
    from updates import update

    api.cache = fakeredis.FakeRedis(decode_responses=True)
    update.ROOT = runtime / 'updates'
    update.CONFIG = ROOT / 'deployment' / 'update-source' / 'update-source.json'
    update.KEY = ROOT / 'deployment' / 'update-source' / 'update-public-key.bin'

    def preview_broker(action, payload=None):
        if action in {'updates.status', 'updates.check'}:
            operation = action.split('.', 1)[1]
            try:
                result = update.action(operation, payload or {})
            except Exception as exc:
                raise HTTPException(409, str(exc)) from exc
            if operation == 'status':
                result.update(install_supported=False, restart_supported=False, preview=True)
            return result
        raise HTTPException(409, 'This action requires your installed AirLink server. This is a local preview.')

    api.broker = preview_broker

    class PreviewIsolation:
        def __init__(self, app):
            self.app = app

        async def __call__(self, scope, receive, send):
            if scope['type'] == 'http' and not local_request(scope['method'], scope['path']):
                response = JSONResponse(status_code=409, content={
                    'detail': 'Local preview: live SAS4, payment, device and appliance operations are disabled. Local account and inventory edits are available.'
                })
                await response(scope, receive, send)
                return
            if scope['type'] == 'websocket' and scope['path'] != '/api/live':
                await send({'type': 'websocket.close', 'code': 1008})
                return
            await self.app(scope, receive, send)

    api.app.add_middleware(PreviewIsolation)
    Base.metadata.create_all(engine)
    migration_path = ROOT / 'database' / 'versions' / 'e29df1458b01_direct_access_roles.py'
    migration_spec = importlib.util.spec_from_file_location('preview_direct_access_roles', migration_path)
    migration = importlib.util.module_from_spec(migration_spec)
    migration_spec.loader.exec_module(migration)
    with engine.begin() as connection:
        migration.consolidate(connection)
    username, password = state['username'], state['password']
    with SessionLocal() as db:
        for name in ('owner', 'manager', 'technician', 'viewer'):
            if db.get(Role, name) is None:
                db.add(Role(name=name))
        db.flush()
        if db.get(Initialization, 1) is None:
            owner = User(username=username, role='owner', password_hash=hasher.hash(password))
            db.add(owner)
            db.flush()
            db.add(Initialization(id=1, owner_id=owner.id))
        db.commit()
    write_private_json(LOGIN_FILE, {
        'username': username, 'password': password,
        'host': args.host, 'port': args.port,
        'note': 'Initial preview password; if changed in My account, use your chosen password.',
    })
    print(f'Local preview login saved to {LOGIN_FILE}', flush=True)
    print('Local preview data persists between restarts; live integration and appliance actions disabled.', flush=True)
    api.app.mount('/', StaticFiles(directory=web_root, html=True), name='dashboard')
    try:
        if args.check:
            from fastapi.testclient import TestClient
            with TestClient(api.app) as client:
                assert client.get('/api/health').status_code == 200
                response = client.post('/api/auth/login', json={'username': username, 'password': password})
                if response.status_code != 200:
                    raise RuntimeError('The initial preview password no longer matches; use the password chosen in My account.')
                session = response.json()
                assert session['user']['role'] == 'owner'
                client.headers.update({'Authorization': 'Bearer ' + session['access_token']})
                for path in ('/api/auth/me', '/api/dashboard', '/api/towers', '/api/devices',
                             '/api/access-roles', '/api/integrations/sas4/device-access',
                             '/api/payments/gateways', '/api/integrations/sas4/device-login-profiles'):
                    assert client.get(path).status_code == 200, path
                for path in ('/api/system/restart', '/api/updates/install',
                             '/api/towers/demo/discover', '/api/payments/users/demo'):
                    assert client.post(path, json={}).status_code == 409, path
                assert client.post('/api/auth/logout').status_code in (200, 204)
                print('Verified owner login, local page reads and preview isolation.', flush=True)
        else:
            uvicorn.run(api.app, host=args.host, port=args.port, access_log=False)
    finally:
        engine.dispose()

if __name__ == '__main__':
    main()
