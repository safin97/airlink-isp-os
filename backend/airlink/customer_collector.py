"""Continuously refresh sessions and device readings independently of browsers."""
import logging
import threading
from sqlalchemy import select
from .db import SessionLocal
from .models import User, SAS4UserConnection
from .customer_probes import service as probes
from .online_sessions import service as sessions

log = logging.getLogger(__name__)
PAGE_SIZE = 32
INTERVAL = 5


class CustomerCollector:
    def __init__(self):
        self.stopped = threading.Event()
        self.thread = None
        self.pages = {}
        self.last_account = ''

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        sessions.start()
        self.stopped.clear()
        self.thread = threading.Thread(target=self.run, name='customer-collector', daemon=True)
        self.thread.start()
        log.info('Customer telemetry background collector started')

    def stop(self):
        self.stopped.set()
        if self.thread:
            self.thread.join(timeout=5)
        sessions.stop()

    def run(self):
        while not self.stopped.is_set():
            try:
                self.poll_once()
            except Exception as exc:
                log.warning('Customer collection cycle failed (%s)', type(exc).__name__)
            if self.stopped.wait(INTERVAL):
                break

    def poll_once(self):
        # Session lists and username matching must refresh even if device probes are busy.
        sessions.refresh_accounts()
        with probes.lock:
            capacity = min(PAGE_SIZE, 64 - len(probes.pending)) if probes.pool is not None else 0
        if capacity <= 0:
            return
        with SessionLocal() as db:
            accounts = list(db.scalars(select(User).join(SAS4UserConnection,
                SAS4UserConnection.user_id == User.id).where(User.active.is_(True))))
            self.pages = {key: value for key, value in self.pages.items() if key in {u.id for u in accounts}}
            accounts.sort(key=lambda user: (user.id <= self.last_account, user.id))
            for user in accounts:
                if self.stopped.is_set():
                    return
                self.last_account = user.id
                try:
                    snapshot = sessions.snapshot(db, user)
                    if not snapshot or snapshot['collection_status'] != 'available':
                        continue
                    rows = snapshot['clients']
                    offset = self.pages.get(user.id, 0)
                    if offset >= len(rows):
                        offset = 0
                    batch = rows[offset:offset + capacity]
                    probes.enrich(db, user, {'clients': batch})
                    self.pages[user.id] = offset + len(batch) if offset + len(batch) < len(rows) else 0
                except Exception as exc:
                    log.debug('Customer account collection deferred (%s)', type(exc).__name__)
                return


service = CustomerCollector()
