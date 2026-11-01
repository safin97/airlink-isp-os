"""Probe the installed QA guest without printing credentials or bearer tokens."""
import json
import sys
import time
import ssl
from websockets.sync.client import connect
from pathlib import Path
import httpx

ROOT=Path(__file__).resolve().parents[1]
credentials=json.loads(Path('/tmp/airlink-qemu-test-credentials.json').read_text())
with httpx.Client(base_url='https://127.0.0.1:18443',verify=False,timeout=20) as client:
    response=client.post('/api/auth/login',json=credentials)
    response.raise_for_status()
    client.headers['Authorization']='Bearer '+response.json()['access_token']
    assert client.get('/api/setup/status').json()['initialized'] is True
    assert client.get('/api/auth/me').json()['role']=='owner'
    assert client.get('/api/dashboard').json()['availability_24h'] is None
    system=client.get('/api/system');system.raise_for_status()
    assert all(v=='active' for v in system.json()['services'].values()),system.text
    network=client.get('/api/network');network.raise_for_status()
    if sys.argv[1:]==['websocket']:
        with connect('wss://127.0.0.1:18443/api/ws',ssl=ssl._create_unverified_context()) as ws:
            ws.send(json.dumps({'token':response.json()['access_token']}))
            assert json.loads(ws.recv(timeout=15))['devices']==0
        print('QA_INSTALLED_HTTPS_WEBSOCKET_OK')
    elif sys.argv[1:]==['apply-rollback-test']:
        before=network.json()
        device=next(x['ifname'] for x in before['addresses'] if x['ifname']!='lo' and any(a.get('scope')=='global' for a in x.get('addr_info',[])))
        result=client.post('/api/network/apply',json={'interface':device,'method':'dhcp','hostname':'airlink'})
        result.raise_for_status()
        (ROOT/'test-results/network-rollback-state.json').write_text(json.dumps({'before':before['interfaces'],'checkpoint':result.json()['checkpoint'],'applied_at':time.time()},indent=2))
        print('QA_NETWORK_CHECKPOINT_APPLIED; awaiting NetworkManager timeout')
    elif sys.argv[1:]==['verify-rollback']:
        old=json.loads((ROOT/'test-results/network-rollback-state.json').read_text())
        if time.time()-old['applied_at']<125:raise SystemExit('Wait until the 120-second rollback deadline has passed')
        after=network.json()['interfaces']
        assert after==old['before'],(old['before'],after)
        result=client.post('/api/network/confirm',json={'checkpoint':old['checkpoint']})
        assert result.status_code==409,result.text
        print('QA_NETWORK_TIMED_ROLLBACK_VERIFIED')
    print('QA_INSTALLED_OWNER_API_SERVICES_OK')
