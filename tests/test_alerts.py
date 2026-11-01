from airlink.db import SessionLocal
from airlink.models import Tower,Device,Metric,Alert,now
from monitoring.alerts import evaluate
from sqlalchemy import select


def test_alert_opens_once_and_resolves(client):
    with SessionLocal() as db:
        t=Tower(name='T');db.add(t);db.flush()
        d=Device(name='D',tower_id=t.id,ip_address='192.0.2.1',status='offline',last_poll=now(),poll_interval=60,cpu_threshold=90)
        db.add(d);db.flush()
        m=Metric(device_id=d.id,values={'icmp_up':False})
        evaluate(db,d,m);db.commit()
        evaluate(db,d,m);db.commit()
        assert len(db.scalars(select(Alert)).all())==1
        d.status='online';evaluate(db,d,m);db.commit()
        assert db.scalar(select(Alert)).resolved_at is not None
