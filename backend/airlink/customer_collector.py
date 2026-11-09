"""Collect online customer telemetry independently of browser sessions."""
import logging
import threading
import time
from sqlalchemy import select
from .db import SessionLocal
from .models import User, SAS4UserConnection
from .security import cipher
from . import section_access
from .customer_probes import configuration, service as probes

log = logging.getLogger(__name__)
PAGE_SIZE = 7
INTERVAL = 5


class CustomerCollector:
    def __init__(self):
        self.stopped = threading.Event()
        self.thread = None
        self.pages = {}
        self.retry_at = {}
        self.last_account = ''

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.stopped.clear()
        self.thread = threading.Thread(target=self.run, name='customer-collector', daemon=True)
        self.thread.start()
        log.info('Customer telemetry background collector started')

    def stop(self):
        self.stopped.set()

    def run(self):
        while not self.stopped.is_set():
            try:
                self.poll_once()
            except Exception as exc:
                # Exception text can contain upstream credentials or customer data.
                log.warning('Customer collection cycle failed (%s)', type(exc).__name__)
            if self.stopped.wait(INTERVAL):
                break

    def poll_once(self):
        from . import sas4
        # Keep the device queue bounded and leave room for interactive checks.
        with probes.lock:
            if probes.pool is None or len(probes.pending) > 32 - PAGE_SIZE:
                return
        with SessionLocal() as db:
            accounts = db.execute(select(User, SAS4UserConnection).join(
                SAS4UserConnection, SAS4UserConnection.user_id == User.id
            ).where(User.active.is_(True)).order_by(User.id)).all()
            ids = {user.id for user, _ in accounts}
            self.pages = {key: value for key, value in self.pages.items() if key in ids}
            self.retry_at = {key: value for key, value in self.retry_at.items() if key in ids}
            # Rotate across accounts, advancing each account through every online page.
            accounts.sort(key=lambda pair: (pair[0].id <= self.last_account, pair[0].id))
            for user, connection in accounts:
                if self.stopped.is_set():
                    return
                self.last_account = user.id
                if self.retry_at.get(user.id, 0) > time.monotonic():
                    continue
                try:
                    sas4.sas4_access(user)
                    section_access.enforce_request(user, 'GET', '/api/integrations/sas4/online')
                    config = configuration(db, user)
                    if not config['enabled'] or not connection.encrypted_password:
                        continue
                    if not config.get('snmp_candidates') and not (
                            config.get('api_username') and config.get('api_password')):
                        continue
                    page = self.pages.get(user.id, 1)
                    password = cipher().decrypt(connection.encrypted_password.encode()).decode()
                    result = sas4.fetch_clients(connection, password, page=page, count=PAGE_SIZE, online=True)
                    if self.stopped.is_set():
                        return
                    probes.enrich(db, user, result)
                    self.pages[user.id] = page + 1 if page < result['last_page'] else 1
                    self.retry_at.pop(user.id, None)
                except Exception as exc:
                    self.retry_at[user.id] = time.monotonic() + 60
                    log.debug('Customer account collection deferred (%s)', type(exc).__name__)
                return


service = CustomerCollector()
