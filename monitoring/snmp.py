"""Read-only SNMP v1/v2c/v3 with bounded standard and verified vendor MIB walks."""
from pysnmp.proto.rfc1905 import NoSuchObject, NoSuchInstance, EndOfMibView
from pysnmp.hlapi.v3arch.asyncio import (SnmpEngine, CommunityData, UsmUserData, UdpTransportTarget, ContextData,
    ObjectType, ObjectIdentity, get_cmd, walk_cmd, USM_AUTH_HMAC192_SHA256, USM_PRIV_CFB128_AES)

# SNMPv2-MIB RFC 3418, IF-MIB RFC 2863, HOST-RESOURCES-MIB RFC 2790.
UPTIME = "1.3.6.1.2.1.1.3.0"
TABLES = {
    "if_name": "1.3.6.1.2.1.31.1.1.1.1",
    "if_type": "1.3.6.1.2.1.2.2.1.3",
    "if_status": "1.3.6.1.2.1.2.2.1.8",
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
    if version in ("1", "2c"):
        return CommunityData(credentials["community"], mpModel=0 if version == "1" else 1)
    if version != "3":
        raise ValueError("Unsupported SNMP version")
    return UsmUserData(credentials["username"], credentials["auth_key"], credentials["priv_key"],
                       authProtocol=USM_AUTH_HMAC192_SHA256, privProtocol=USM_PRIV_CFB128_AES)


async def read_table(engine, auth, target, oid, textual=False):
    rows = {}
    async for error, status, _, binds in walk_cmd(engine, auth, target, ContextData(), ObjectType(ObjectIdentity(oid)),
                                                 lexicographicMode=False, lookupMib=False, maxRows=256):
        if error or status or not binds:
            break
        for key, value in binds:
            if isinstance(value, (NoSuchObject, NoSuchInstance, EndOfMibView)):
                continue
            key = str(key)
            if not key.startswith(oid + "."):
                continue
            try:
                rows[key[len(oid) + 1:]] = str(value) if textual else int(value)
            except (ValueError, TypeError):
                pass
        if len(rows) >= 256:
            break
    return rows


async def collect(address, credentials, retries, vendor="generic"):
    auth = authentication(credentials)
    engine = SnmpEngine()
    try:
        target = await UdpTransportTarget.create((address, 161), timeout=1, retries=retries)
        error, status, _, binds = await get_cmd(engine, auth, target, ContextData(), ObjectType(ObjectIdentity(UPTIME)), lookupMib=False)
        if error or status:
            raise RuntimeError("SNMP request failed (check version, credentials and device ACL)")
        uptime = int(binds[0][1]) / 100
        values = {"uptime_seconds": uptime, "snmp_up": True}
        if vendor == "auto":
            error, status, _, identity = await get_cmd(engine, auth, target, ContextData(),
                ObjectType(ObjectIdentity("1.3.6.1.2.1.1.2.0")), lookupMib=False)
            oid = str(identity[0][1]) if not error and not status and identity else ""
            vendor = ("mikrotik" if oid == "1.3.6.1.4.1.14988" or oid.startswith("1.3.6.1.4.1.14988.")
                      else "ubiquiti" if oid == "1.3.6.1.4.1.41112" or oid.startswith(("1.3.6.1.4.1.41112.", "1.3.6.1.4.1.10002."))
                      else "generic")
            values["detected_vendor"] = vendor
        tables = {}
        for name, oid in TABLES.items():
            if credentials.get("version") == "1" and name in ("if_rx_octets", "if_tx_octets"):
                tables[name] = {}  # SNMPv1 cannot carry Counter64 values.
            else:
                tables[name] = await read_table(engine, auth, target, oid, name in ("if_name", "storage_type"))
        for name, oid in FALLBACK_TABLES.items():
            tables[name] = await read_table(engine, auth, target, oid, name == "if_descr")
        if tables["cpu"]:
            values["cpu_percent"] = sum(tables["cpu"].values()) / len(tables["cpu"])
        memory = [i for i, kind in tables["storage_type"].items() if kind == RAM_TYPE and all(i in tables[k] for k in ("storage_units", "storage_size", "storage_used"))]
        total = sum(tables["storage_size"].get(i, 0) * tables["storage_units"].get(i, 0) for i in memory)
        used = sum(tables["storage_used"].get(i, 0) * tables["storage_units"].get(i, 0) for i in memory)
        if total:
            values.update(memory_total_bytes=total, memory_used_bytes=used, memory_percent=100 * used / total)
        interfaces = {}
        for index in tables["if_name"].keys() | tables["if_descr"].keys() | tables["if_status"].keys():
            if not index.isdecimal():
                continue
            interface = {"name": tables["if_name"].get(index) or tables["if_descr"].get(index) or index}
            for field in ("type", "status", "discontinuity"):
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
        for name, oid in WIRELESS_TABLES.get(family, {}).items():
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
        return values
    finally:
        engine.close_dispatcher()
