"""Read-only, bounded SNMP identity discovery without an ICMP prerequisite."""
import asyncio
import json
from sqlalchemy import select
from .models import SNMPProfile
from .security import cipher
from .vendor_identity import identify_vendor, VENDOR_LABELS

BATCH_SIZE = 32


def candidates(db, profile_id=None):
    query = select(SNMPProfile).order_by(SNMPProfile.name)
    if profile_id:
        query = query.where(SNMPProfile.id == profile_id)
    profiles = list(db.scalars(query.limit(17)))
    if profile_id and not profiles:
        raise ValueError('SNMP profile not found')
    if len(profiles) > 16:
        raise ValueError('Select one SNMP profile when more than 16 profiles are saved')
    result = []
    for profile in profiles:
        credentials = json.loads(cipher().decrypt(profile.encrypted_credentials.encode()))
        result.append({'profile_id': profile.id, 'profile_name': profile.name,
                       'credentials': credentials})
    if not profile_id:
        for version in ('2c', '1'):
            if not any(c['credentials'].get('version') == version and
                       c['credentials'].get('community') == 'public' for c in result):
                result.append({'profile_id': None, 'profile_name': 'public',
                               'credentials': {'version': version, 'community': 'public'}})
    return result


async def identify(address, profiles):
    from monitoring.snmp import (SnmpEngine, UdpTransportTarget, ContextData,
        ObjectType, ObjectIdentity, get_cmd, authentication)
    from pysnmp.proto.rfc1905 import NoSuchObject, NoSuchInstance, EndOfMibView
    engine = SnmpEngine()
    try:
        target = await UdpTransportTarget.create((address, 161), timeout=1, retries=0)
        for profile in profiles:
            credentials = profile['credentials']
            try:
                auth = authentication(credentials)
                error, status, _, binds = await get_cmd(engine, auth, target, ContextData(),
                    ObjectType(ObjectIdentity('1.3.6.1.2.1.1.2.0')),
                    ObjectType(ObjectIdentity('1.3.6.1.2.1.1.1.0')), lookupMib=False)
                if error or status or not binds:
                    continue
                values = [str(value) if not isinstance(value, (NoSuchObject, NoSuchInstance, EndOfMibView)) else ''
                          for _, value in binds]
                if not any(values):
                    continue
                vendor = identify_vendor(values[0], values[1] if len(values) > 1 else '')
                name = ''
                error, status, _, names = await get_cmd(engine, auth, target, ContextData(),
                    ObjectType(ObjectIdentity('1.3.6.1.2.1.1.5.0')), lookupMib=False)
                if not error and not status and names and not isinstance(names[0][1], (NoSuchObject, NoSuchInstance, EndOfMibView)):
                    name = str(names[0][1])[:120]
                return {'ip_address': address, 'name': name or f'{VENDOR_LABELS[vendor]} {address}',
                        'vendor': vendor, 'vendor_label': VENDOR_LABELS[vendor],
                        'snmp_version': credentials.get('version', '3'),
                        'snmp_profile_id': profile['profile_id'], 'profile_name': profile['profile_name']}
            except Exception:
                continue
        return None
    finally:
        engine.close_dispatcher()


async def scan_batch(addresses, profiles):
    async def bounded(address):
        try:
            return await asyncio.wait_for(identify(address, profiles), timeout=25), False
        except asyncio.TimeoutError:
            return None, True
        except Exception:
            return None, False
    results = await asyncio.gather(*(bounded(address) for address in addresses[:BATCH_SIZE]))
    return [row for row, _ in results if row], any(timed_out for _, timed_out in results)
