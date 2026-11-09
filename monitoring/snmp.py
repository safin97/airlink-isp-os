"""Read-only SNMP v1/v2c/v3 with bounded standard and verified vendor MIB walks."""
from airlink.vendor_identity import identify_vendor
from airlink.wireless_clients import ssids
from pysnmp.proto.rfc1905 import NoSuchObject, NoSuchInstance, EndOfMibView
from pysnmp.hlapi.v3arch.asyncio import (SnmpEngine, CommunityData, UsmUserData, UdpTransportTarget, ContextData,
    ObjectType, ObjectIdentity, get_cmd, walk_cmd, bulk_walk_cmd, USM_AUTH_HMAC192_SHA256, USM_AUTH_HMAC96_SHA, USM_AUTH_HMAC96_MD5, USM_PRIV_CFB128_AES, USM_PRIV_CBC56_DES)

# SNMPv2-MIB RFC 3418, IF-MIB RFC 2863, HOST-RESOURCES-MIB RFC 2790.
UPTIME = "1.3.6.1.2.1.1.3.0"
TABLES = {
    "if_name": "1.3.6.1.2.1.31.1.1.1.1",
    "if_type": "1.3.6.1.2.1.2.2.1.3",
    "if_status": "1.3.6.1.2.1.2.2.1.8",
    "if_admin_status": "1.3.6.1.2.1.2.2.1.7",
    "if_speed_mbps": "1.3.6.1.2.1.31.1.1.1.15",
    "if_rx_octets": "1.3.6.1.2.1.31.1.1.1.6",
    "if_tx_octets": "1.3.6.1.2.1.31.1.1.1.10",
    "if_discontinuity": "1.3.6.1.2.1.31.1.1.1.19",
    "cpu": "1.3.6.1.2.1.25.3.3.1.2",
    "storage_type": "1.3.6.1.2.1.25.2.3.1.2",
    "storage_units": "1.3.6.1.2.1.25.2.3.1.4",
    "storage_size": "1.3.6.1.2.1.25.2.3.1.5",
    "storage_used": "1.3.6.1.2.1.25.2.3.1.6",
}
FALLBACK_TABLES = {
    "if_descr": "1.3.6.1.2.1.2.2.1.2",
    "if_speed": "1.3.6.1.2.1.2.2.1.5",
    "if_rx32": "1.3.6.1.2.1.2.2.1.10",
    "if_tx32": "1.3.6.1.2.1.2.2.1.16",
}
# Vendor-published MIBs and revision/source links are recorded in docs/MONITORING.md.
WIRELESS_TABLES = {
    "mikrotik": {
        "client_count": "1.3.6.1.4.1.14988.1.1.1.3.1.6",
        "frequency_mhz": "1.3.6.1.4.1.14988.1.1.1.3.1.7",
        "signal_dbm": "1.3.6.1.4.1.14988.1.1.1.2.1.3",
    },
    "ubiquiti": {
        "client_count": "1.3.6.1.4.1.41112.1.4.5.1.15",
        "frequency_mhz": "1.3.6.1.4.1.41112.1.4.1.1.4",
        "signal_dbm": "1.3.6.1.4.1.41112.1.4.5.1.5",
        "noise_dbm": "1.3.6.1.4.1.41112.1.4.5.1.8",
    },
}
RAM_TYPE = "1.3.6.1.2.1.25.2.1.2"
STATION_TABLES = {
    'mikrotik': {
        'station_signal_dbm': '1.3.6.1.4.1.14988.1.1.1.1.1.4',
        'ssid': '1.3.6.1.4.1.14988.1.1.1.1.1.5',
    },
    'ubiquiti': {'ssid': '1.3.6.1.4.1.41112.1.4.5.1.2'},
}


def counter_rate(previous, current, seconds, rebooted=False, discontinuity_changed=False):
    if previous is None or current is None or seconds <= 0 or rebooted or discontinuity_changed or current < previous:
        return None
    return (current - previous) * 8 / seconds


def interface_rate(previous, current, direction, seconds, rebooted=False):
    bits = current.get("counter_bits", 64)
    if bits != previous.get("counter_bits", 64):
        return None
    if bits == 32 and (not current.get("speed_mbps") or
                      current["speed_mbps"] * 1_000_000 * seconds / 8 >= 2**32):
        return None  # A full wrap at link speed makes the delta ambiguous.
    return counter_rate(previous.get(direction + "_octets"), current.get(direction + "_octets"),
                        seconds, rebooted, current.get("discontinuity") != previous.get("discontinuity"))


def authentication(credentials):
    version = credentials.get("version", "3")  # Existing encrypted profiles remain v3.
    if version in ("1", "2", "2c"):
        return CommunityData(credentials["community"], mpModel=0 if version == "1" else 1)
    if version != "3":
        raise ValueError("Unsupported SNMP version")
    return UsmUserData(credentials["username"], credentials["auth_key"], credentials["priv_key"],
                       authProtocol={'SHA256': USM_AUTH_HMAC192_SHA256, 'SHA1': USM_AUTH_HMAC96_SHA, 'MD5': USM_AUTH_HMAC96_MD5}[credentials.get('auth_protocol', 'SHA256')],
                       privProtocol={'AES128': USM_PRIV_CFB128_AES, 'DES': USM_PRIV_CBC56_DES}[credentials.get('priv_protocol', 'AES128')])


async def read_table(engine, auth, target, oid, textual=False):
    rows = {}
    # v2 GETBULK avoids one round trip per interface on RouterOS. Older agents
    # that reject bulk requests retain the GETNEXT compatibility path.
    modes = (True, False) if getattr(auth, 'message_processing_model', None) == 1 else (False,)
    for bulk in modes:
        args = (engine, auth, target, ContextData())
        iterator = (bulk_walk_cmd(*args, 0, 10, ObjectType(ObjectIdentity(oid)),
                    lexicographicMode=False, lookupMib=False, maxRows=256) if bulk else
                    walk_cmd(*args, ObjectType(ObjectIdentity(oid)),
                    lexicographicMode=False, lookupMib=False, maxRows=256))
        failed = False
        async for error, status, _, binds in iterator:
            if error or status:
                failed = True
                break
            if not binds:
                break
            for key, value in binds:
                if isinstance(value, (NoSuchObject, NoSuchInstance, EndOfMibView)):
                    continue
                key = str(key)
                if not key.startswith(oid + "."):
                    continue
                try:
                    rows[key[len(oid) + 1:]] = str(value)[:128] if textual else int(value)
                except (ValueError, TypeError):
                    pass
                if len(rows) >= 256:
                    break
            if len(rows) >= 256:
                break
        await iterator.aclose()
        if rows or not failed:
            break
    return rows


async def collect(address, credentials, retries, vendor="generic", link_only=False, timeout=1):
    if vendor == 'mikrotik_switch':
        vendor = 'mikrotik'
    auth = authentication(credentials)
    engine = SnmpEngine()
    try:
        target = await UdpTransportTarget.create((address, 161), timeout=timeout, retries=retries)
        error, status, _, binds = await get_cmd(engine, auth, target, ContextData(), ObjectType(ObjectIdentity(UPTIME)), lookupMib=False)
        if error or status:
            raise RuntimeError("SNMP request failed (check version, credentials and device ACL)")
        uptime = int(binds[0][1]) / 100
        values = {"uptime_seconds": uptime, "snmp_up": True}
        if vendor == "auto":
            error, status, _, identity = await get_cmd(engine, auth, target, ContextData(),
                ObjectType(ObjectIdentity("1.3.6.1.2.1.1.2.0")),
                ObjectType(ObjectIdentity("1.3.6.1.2.1.1.1.0")), lookupMib=False)
            oid = str(identity[0][1]) if not error and not status and identity else ""
            description = str(identity[1][1]) if not error and not status and len(identity or []) > 1 else ""
            vendor = identify_vendor(oid, description)
            values.update(detected_vendor=vendor, vendor_detection_source='SNMP')
        tables = {}
        for name, oid in TABLES.items():
            if link_only and name not in ("if_name", "if_type", "if_status", "if_speed_mbps"):
                tables[name] = {}
            elif credentials.get("version") == "1" and name in ("if_rx_octets", "if_tx_octets"):
                tables[name] = {}  # SNMPv1 cannot carry Counter64 values.
            else:
                tables[name] = await read_table(engine, auth, target, oid, name in ("if_name", "storage_type"))
        for name, oid in FALLBACK_TABLES.items():
            tables[name] = {} if link_only and name not in ("if_descr", "if_speed") else await read_table(engine, auth, target, oid, name == "if_descr")
        if tables["cpu"]:
            values["cpu_percent"] = sum(tables["cpu"].values()) / len(tables["cpu"])
        memory = [i for i, kind in tables["storage_type"].items() if kind == RAM_TYPE and all(i in tables[k] for k in ("storage_units", "storage_size", "storage_used"))]
        total = sum(tables["storage_size"].get(i, 0) * tables["storage_units"].get(i, 0) for i in memory)
        used = sum(tables["storage_used"].get(i, 0) * tables["storage_units"].get(i, 0) for i in memory)
        if total:
            values.update(memory_total_bytes=total, memory_used_bytes=used, memory_percent=100 * used / total)
        interfaces = {}
        for index in tables["if_name"].keys() | tables["if_descr"].keys() | tables["if_status"].keys() | tables["if_type"].keys():
            if not index.isdecimal():
                continue
            interface = {"name": tables["if_name"].get(index) or tables["if_descr"].get(index) or index}
            for field in ("type", "status", "admin_status", "discontinuity"):
                if index in tables["if_" + field]:
                    interface[field] = tables["if_" + field][index]
            speed = tables["if_speed_mbps"].get(index)
            if not speed and 0 < tables["if_speed"].get(index, 0) < 2**32 - 1:
                speed = tables["if_speed"][index] / 1_000_000
            if speed:
                interface["speed_mbps"] = speed
            high = all(index in tables["if_" + direction + "_octets"] for direction in ("rx", "tx"))
            interface["counter_bits"] = 64 if high else 32
            for direction in ("rx", "tx"):
                table = tables["if_" + direction + ("_octets" if high else "32")]
                if index in table and 0 <= table[index] < 2**interface["counter_bits"]:
                    interface[direction + "_octets"] = table[index]
            interfaces[index] = interface
        values["interfaces"] = interfaces
        family = "ubiquiti" if vendor in ("ubiquiti", "ubiquiti_m5", "ubiquiti_ac") else vendor
        wireless = {}
        for name, oid in STATION_TABLES.get(family, {}).items():
            table = await read_table(engine, auth, target, oid, textual=name == 'ssid')
            table = {index: value for index, value in table.items() if
                     (name == 'ssid' and isinstance(value, str) and value) or
                     (name == 'station_signal_dbm' and isinstance(value, (int, float)) and -150 <= value < 0)}
            if table:
                wireless[name] = table
        for name, oid in WIRELESS_TABLES.get(family, {}).items():
            if link_only and name != "signal_dbm":
                continue
            if link_only and name == 'signal_dbm' and wireless.get('station_signal_dbm'):
                continue
            table = await read_table(engine, auth, target, oid)
            table = {index: value for index, value in table.items() if
                     (name in ("signal_dbm", "noise_dbm") and -150 <= value < 0) or
                     (name == "frequency_mhz" and 1 <= value <= 65535) or
                     (name == "client_count" and value >= 0)}
            if table:
                wireless[name] = table
        if wireless:
            values["wireless"] = wireless
        if "client_count" in wireless:
            values["wireless_clients"] = sum(wireless["client_count"].values())
        if "signal_dbm" in wireless:
            values["weakest_signal_dbm"] = min(wireless["signal_dbm"].values())
        if "frequency_mhz" in wireless:
            values["radio_frequencies_mhz"] = sorted(set(wireless["frequency_mhz"].values()))
        if not link_only:
            names = dict(wireless.get('ssid', {}))
            if family == 'mikrotik':
                names.update(await read_table(engine, auth, target,
                    '1.3.6.1.4.1.14988.1.1.1.3.1.4', textual=True))
            values['wireless_ssids'] = ssids(names.values())
            registrations = wireless.get('signal_dbm', {}) if family == 'mikrotik' else (
                await read_table(engine, auth, target, '1.3.6.1.4.1.41112.1.4.7.1.3')
                if family == 'ubiquiti' else {})
            clients = []
            for index, strength in registrations.items():
                parts = index.split('.')
                if len(parts) != 7 or not all(part.isdecimal() for part in parts):
                    continue
                octets, interface = (parts[:6], parts[6]) if family == 'mikrotik' else (parts[1:], parts[0])
                if any(int(part) > 255 for part in octets):
                    continue
                clients.append({'mac_address': ':'.join(f'{int(part):02X}' for part in octets),
                    'interface': interfaces.get(interface, {}).get('name', interface),
                    'ssid': names.get(interface, ''),
                    'signal_dbm': strength if -150 <= strength < 0 else None})
            if clients or values.get('wireless_clients') == 0:
                values['wireless_registrations'] = clients
                values['wireless_registration_source'] = 'SNMP'
            if clients and 'wireless_clients' not in values:
                values['wireless_clients'] = len(clients)
        return values
    finally:
        engine.close_dispatcher()
