"""Standard MIBs only. Vendor-specific wireless fields remain unavailable."""
import asyncio
from pysnmp.hlapi.v3arch.asyncio import (SnmpEngine, UsmUserData, UdpTransportTarget, ContextData,
    ObjectType, ObjectIdentity, get_cmd, walk_cmd, USM_AUTH_HMAC192_SHA256, USM_PRIV_CFB128_AES)

# SNMPv2-MIB RFC 3418, IF-MIB RFC 2863, HOST-RESOURCES-MIB RFC 2790.
UPTIME = "1.3.6.1.2.1.1.3.0"
TABLES = {
    "if_name": "1.3.6.1.2.1.31.1.1.1.1",
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
RAM_TYPE = "1.3.6.1.2.1.25.2.1.2"


def counter_rate(previous, current, seconds, rebooted=False, discontinuity_changed=False):
    if previous is None or current is None or seconds <= 0 or rebooted or discontinuity_changed or current < previous:
        return None
    return (current - previous) * 8 / seconds


async def collect(address, credentials, retries):
    engine = SnmpEngine()
    auth = UsmUserData(credentials["username"], credentials["auth_key"], credentials["priv_key"],
                       authProtocol=USM_AUTH_HMAC192_SHA256, privProtocol=USM_PRIV_CFB128_AES)
    target = await UdpTransportTarget.create((address, 161), timeout=1, retries=retries)
    try:
        error, status, _, binds = await get_cmd(engine, auth, target, ContextData(), ObjectType(ObjectIdentity(UPTIME)), lookupMib=False)
        if error or status:
            raise RuntimeError("SNMPv3 request failed (check reachability and authPriv settings)")
        uptime = int(binds[0][1]) / 100
        values = {"uptime_seconds": uptime, "snmp_up": True}
        tables = {}
        for name, oid in TABLES.items():
            rows = {}
            async for error, status, _, binds in walk_cmd(engine, auth, target, ContextData(), ObjectType(ObjectIdentity(oid)),
                                                         lexicographicMode=False, lookupMib=False, maxRows=256):
                if error or status:
                    break
                for key, value in binds:
                    key = str(key)
                    if not key.startswith(oid + "."):
                        continue
                    try:
                        rows[key[len(oid) + 1:]] = int(value) if name not in ("if_name", "storage_type") else str(value)
                    except (ValueError, TypeError):
                        pass
                if len(rows) >= 256:
                    break
            tables[name] = rows
        if tables["cpu"]:
            values["cpu_percent"] = sum(tables["cpu"].values()) / len(tables["cpu"])
        memory = [i for i, kind in tables["storage_type"].items() if kind == RAM_TYPE and all(i in tables[k] for k in ("storage_units", "storage_size", "storage_used"))]
        total = sum(tables["storage_size"].get(i, 0) * tables["storage_units"].get(i, 0) for i in memory)
        used = sum(tables["storage_used"].get(i, 0) * tables["storage_units"].get(i, 0) for i in memory)
        if total:
            values.update(memory_total_bytes=total, memory_used_bytes=used, memory_percent=100 * used / total)
        values["interfaces"] = {i: {key.removeprefix("if_"): table[i] for key, table in tables.items() if key.startswith("if_") and i in table}
                                for i in tables["if_name"]}
        return values
    finally:
        engine.close_dispatcher()
