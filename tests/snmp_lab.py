"""Run only with a disposable local Net-SNMP agent; not a vendor hardware test."""
import asyncio
from monitoring.snmp import collect

async def main():
    for version in ('1', '2c', '3'):
        credentials = {'version': version, 'community': 'airlink-read-only-lab'} if version != '3' else {
            'username': 'airlinklab', 'auth_key': 'Lab-authentication-2026', 'priv_key': 'Lab-privacy-key-2026'}
        values = await collect('127.0.0.1', credentials, 0)
        assert values['snmp_up'] is True and values['uptime_seconds'] >= 0
        assert values['interfaces']
        assert any('rx_octets' in interface for interface in values['interfaces'].values())
        if version == '1':
            assert all(interface['counter_bits'] == 32 for interface in values['interfaces'].values())
        assert 0 <= values['memory_percent'] <= 100
        assert 'wireless_clients' not in values
        print('SNMP_VERSION_' + version + '_LAB_OK', flush=True)
        wrong = {**credentials, **({'auth_key': 'Wrong-authentication-key'} if version == '3' else {'community': 'wrong-community'})}
        try:
            await collect('127.0.0.1', wrong, 0)
        except RuntimeError:
            print('SNMP_VERSION_' + version + '_WRONG_CREDENTIAL_REJECTED', flush=True)
        else:
            raise AssertionError('Wrong SNMP credentials were accepted')
asyncio.run(main())
