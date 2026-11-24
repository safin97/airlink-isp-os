"""Keep each permitted account's dashboard station current without an open browser."""
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from sqlalchemy import select
from fastapi import HTTPException
from . import deye
from .db import SessionLocal
from .models import DeyeConnection, User, now

log = logging.getLogger(__name__)
INTERVAL = deye.CACHE_SECONDS
WORKERS = 4


def poll_account(user_id):
    with SessionLocal() as db:
        user = db.get(User, user_id)
        if user is None:
            return
        with deye.lock_for(user):
            db.expire_all()
            from .section_access import has_capability
            if not user.active or not has_capability(user, 'deye_management', db):
                return
            try:
                deye.access(user, db)
            except HTTPException:
                return
            row = db.get(DeyeConnection, user_id)
            if row is None:
                return
            selected = row.dashboard_station
            try:
                if selected is None:
                    stations = deye.station_page(row, 1)['stations']
                    selected = stations[0] if stations else None
                if selected:
                    deye.read_station(db, row, selected['id'])
                row.cache = {**(row.cache or {}), 'monitor': {
                    'station': selected, 'checked_at': now().isoformat(), 'error': False}}
                db.commit()
                if selected:
                    cached = deye.reading_cache(row).get(selected['id'], {})
                    return max(1, cached.get('at', time.time()) + INTERVAL - time.time())
            except Exception:
                # Never log cloud responses, account credentials or tokens.
                db.rollback()
                row = db.get(DeyeConnection, user_id)
                if row:
                    row.cache = {**(row.cache or {}), 'monitor': {
                        'station': selected, 'checked_at': now().isoformat(), 'error': True}}
                    db.commit()
                return deye.ERROR_CACHE_SECONDS


class DeyeMonitor:
    def __init__(self):
        self.stop_event = threading.Event()
        self.thread = None

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.stop_event.clear()
        self.thread = threading.Thread(target=self.run, name='airlink-deye', daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=5)

    def run(self):
        pending, due = {}, {}
        # One API process owns the monitor (as configured by airlink-api.service).
        # Bounded concurrency prevents a slow account from blocking every station.
        with ThreadPoolExecutor(max_workers=WORKERS, thread_name_prefix='deye-cloud') as pool:
            while not self.stop_event.is_set():
                try:
                    for uid, future in list(pending.items()):
                        if future.done():
                            del pending[uid]
                            try:
                                delay = future.result()
                                due[uid] = time.monotonic() + (delay if delay is not None else INTERVAL)
                            except Exception:
                                log.warning('Deye monitoring iteration failed; retrying automatically')
                    with SessionLocal() as db:
                        ids = list(db.scalars(select(DeyeConnection.user_id).join(
                            User, User.id == DeyeConnection.user_id).where(User.active.is_(True))))
                    due = {uid: due.get(uid, 0) for uid in ids}
                    for uid in sorted(ids, key=lambda uid: due[uid]):
                        if len(pending) >= WORKERS or self.stop_event.is_set():
                            break
                        if uid not in pending and time.monotonic() >= due[uid]:
                            pending[uid] = pool.submit(poll_account, uid)
                            due[uid] = time.monotonic() + INTERVAL
                except Exception:
                    log.warning('Deye monitor could not read connections; retrying automatically')
                self.stop_event.wait(1)


service = DeyeMonitor()
