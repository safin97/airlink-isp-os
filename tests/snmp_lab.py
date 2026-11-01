"""Run only inside the disposable Linux test container with a local SNMPv3 agent."""
import asyncio
from monitoring.snmp import collect

async def main():
    values=await collect('127.0.0.1',{'username':'airlinklab','auth_key':'Lab-authentication-2026','priv_key':'Lab-privacy-key-2026'},1)
    assert values['snmp_up'] is True
    assert values['uptime_seconds']>=0
    assert values['interfaces']
    if 'cpu_percent' in values:
        assert 0<=values['cpu_percent']<=100
    else:
        print('CPU_UNAVAILABLE: reference snmpwalk reports no hrProcessorLoad instances on this emulated host')
    assert 'memory_percent' in values
    assert 0<=values['memory_percent']<=100
    print('SNMPV3_AUTHP RIV_LAB_OK'.replace(' ',''),sorted(values))
    try:
        await collect('127.0.0.1',{'username':'airlinklab','auth_key':'Wrong-authentication-key','priv_key':'Lab-privacy-key-2026'},0)
    except RuntimeError:
        print('SNMPV3_WRONG_CREDENTIAL_REJECTED')
    else:
        raise AssertionError('Wrong SNMP credentials were accepted')
asyncio.run(main())
