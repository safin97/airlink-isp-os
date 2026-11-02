import asyncio
import json
import logging
import time
from datetime import timedelta
from sqlalchemy import select, delete
from redis import Redis
from airlink.config import settings
from airlink.db import SessionLocal
from airlink.models import Device, SNMPProfile, Metric, Interface, Alert, now
from airlink.security import aware, cipher
from .snmp import collect, interface_rate

log = logging.getLogger("airlink.monitor")
cache = Redis.from_url(settings.redis_url, socket_connect_timeout=2, socket_timeout=2)


async def ping(address, retries):
    for _ in range(retries + 1):
        proc = await asyncio.create_subprocess_exec("ping", "-n", "-c", "1", "-W", "2", address,
                                                    stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
        try:
            await asyncio.wait_for(proc.wait(), timeout=4)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
        if proc.returncode == 0:
            return True
    return False


async def poll(device_id, semaphore):
    async with semaphore:
        lock = cache.lock("poll:" + device_id, timeout=120, blocking=False)
        if not lock.acquire(blocking=False):
            return
        try:
            with SessionLocal() as db:
                device = db.get(Device, device_id)
                if not device or not device.enabled:
                    return
                values = {"icmp_up": await ping(device.ip_address, device.retries)}
                if device.snmp_profile_id:
                    profile = db.get(SNMPProfile, device.snmp_profile_id)
                    try:
                        credentials = json.loads(cipher().decrypt(profile.encrypted_credentials.encode()))
                        values.update(await asyncio.wait_for(collect(device.ip_address, credentials, device.retries, vendor=device.vendor), timeout=45))
                    except Exception:
                        values.update(snmp_up=False, snmp_error="SNMP unavailable; check version, credentials, ACL and supported MIBs")
                timestamp = now()
                previous = db.scalar(select(Metric).where(Metric.device_id == device_id).order_by(Metric.collected_at.desc()).limit(1))
                if previous and "interfaces" in values:
                    elapsed = (timestamp - aware(previous.collected_at)).total_seconds()
                    rebooted = values.get("uptime_seconds", 0) < previous.values.get("uptime_seconds", 0)
                    for index, interface in values["interfaces"].items():
                        old = previous.values.get("interfaces", {}).get(index, {})
                        for direction in ("rx", "tx"):
                            rate = interface_rate(old, interface, direction, elapsed, rebooted)
                            if rate is not None:
                                interface[direction + "_bps"] = rate
                for index, interface in values.get("interfaces", {}).items():
                    obj = db.scalar(select(Interface).where(Interface.device_id == device_id, Interface.if_index == int(index)))
                    if not obj:
                        obj = Interface(device_id=device_id, if_index=int(index))
                        db.add(obj)
                    obj.name = interface.get("name", index)
                    obj.speed_mbps = interface.get("speed_mbps")
                    obj.oper_status = interface.get("status")
                up = values["icmp_up"] or values.get("snmp_up", False)
                device.last_poll = timestamp
                device.failures = 0 if up else device.failures + 1
                if up:
                    device.status = "online"
                    device.last_success = timestamp
                elif device.failures >= device.failure_threshold:
                    device.status = "offline"
                db.add(Metric(device_id=device_id, collected_at=timestamp, values=values))
                db.commit()
        except Exception:
            log.exception("Poll failed for device %s", device_id)
        finally:
            if lock.owned():
                lock.release()


async def main():
    settings.validate()
    semaphore = asyncio.Semaphore(8)
    while True:
        try:
            with SessionLocal() as db:
                ids = [d.id for d in db.scalars(select(Device).where(Device.enabled.is_(True)))
                       if not d.last_poll or (now() - aware(d.last_poll)).total_seconds() >= d.poll_interval]
            await asyncio.gather(*(poll(device_id, semaphore) for device_id in ids))
            cache.set("health:monitor", str(time.time()), ex=180)
        except Exception:
            log.exception("Monitoring iteration failed")
        await asyncio.sleep(5)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
