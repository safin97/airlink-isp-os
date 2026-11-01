import logging
import time
from datetime import timedelta
from sqlalchemy import select, delete
from airlink.db import SessionLocal
from airlink.models import Device, Metric, Alert, now
from airlink.security import aware
from .worker import cache


def evaluate(db, device, metric):
    fresh = device.last_poll and (now() - aware(device.last_poll)).total_seconds() < device.poll_interval * 3 + 30
    conditions = {
        "unreachable": (bool(fresh and device.status == "offline"), "critical", "Device failed its availability threshold"),
        "cpu_high": (bool(fresh and metric and metric.values.get("cpu_percent", 0) >= device.cpu_threshold), "warning", "CPU usage exceeds configured threshold"),
        "snmp_failed": (bool(fresh and metric and metric.values.get("snmp_up") is False), "warning", "SNMPv3 polling failed"),
        "stale": (bool(not fresh), "warning", "Monitoring data is stale or has not arrived"),
    }
    for kind, (active, severity, message) in conditions.items():
        alert = db.scalar(select(Alert).where(Alert.device_id == device.id, Alert.kind == kind, Alert.resolved_at.is_(None)))
        if active and not alert:
            db.add(Alert(device_id=device.id, kind=kind, severity=severity, message=message))
        elif not active and alert:
            alert.resolved_at = now()


def main():
    logging.basicConfig(level=logging.INFO)
    retention_at = 0
    while True:
        lock = cache.lock("alerts:leader", timeout=120, blocking=False)
        try:
            if lock.acquire(blocking=False):
                with SessionLocal() as db:
                    for device in db.scalars(select(Device).where(Device.enabled.is_(True))):
                        metric = db.scalar(select(Metric).where(Metric.device_id == device.id).order_by(Metric.collected_at.desc()).limit(1))
                        evaluate(db, device, metric)
                    if time.time() - retention_at > 3600:
                        db.execute(delete(Metric).where(Metric.collected_at < now() - timedelta(days=30)))
                        retention_at = time.time()
                    db.commit()
                cache.set("health:alerts", str(time.time()), ex=90)
        except Exception:
            logging.exception("Alert iteration failed")
        finally:
            if lock.owned():
                lock.release()
        time.sleep(15)


if __name__ == "__main__":
    main()
