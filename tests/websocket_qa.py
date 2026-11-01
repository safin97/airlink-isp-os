"""Real Uvicorn/WebSocket transport test against the local-only preview fixture."""
import json
import httpx
from websockets.sync.client import connect
from websockets.exceptions import ConnectionClosedError

with httpx.Client(base_url='http://127.0.0.1:18080') as client:
    response=client.post('/api/auth/login',json={'username':'qa-owner','password':'Local-browser-QA-2026!'})
    response.raise_for_status()
    token=response.json()['access_token']
    expected=client.get('/api/dashboard',headers={'Authorization':'Bearer '+token}).json()
    with connect('ws://127.0.0.1:18080/api/ws') as ws:
        ws.send(json.dumps({'token':token}))
        assert json.loads(ws.recv(timeout=5))['devices']==expected['devices']
        client.post('/api/auth/logout',headers={'Authorization':'Bearer '+token}).raise_for_status()
        try:
            ws.recv(timeout=15)
        except ConnectionClosedError as exc:
            assert exc.rcvd.code==4401
        else:
            raise AssertionError('Revoked session remained connected')
print('REAL_UVICORN_WEBSOCKET_AUTH_AND_REVOCATION_OK')
