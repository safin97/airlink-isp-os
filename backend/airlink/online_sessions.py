"""Account-scoped online snapshots refreshed without a browser or login session."""
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
import hashlib
import math
import threading
import time
from types import SimpleNamespace

from sqlalchemy import select
from .db import SessionLocal
from .models import SAS4UserConnection, User, now
from .security import cipher
from . import section_access
from .wireless_clients import username_map

REFRESH_SECONDS = 30
MAX_AGE = 300
MAX_PAGES = 200
PAGE_SIZE = 500
MAX_ROWS = 10000


def connection_key(user, connection):
    return (user.id, hashlib.sha256((connection.username + '\0' + connection.encrypted_password).encode()).hexdigest())


def allowed(user):
    from . import sas4
    sas4.sas4_access(user)
    section_access.enforce_request(user, 'GET', '/api/integrations/sas4/online')


def collect(connection, password, stopped):
    from . import sas4
    rows = []
    deadline = time.monotonic() + 60
    for page in range(1, MAX_PAGES + 1):
        if stopped.is_set() or time.monotonic() > deadline:
            raise RuntimeError('Online collection interrupted')
        result = sas4.fetch_clients(connection, password, page=page, count=PAGE_SIZE, online=True)
        if result['page'] != page:
            raise ValueError('Invalid online pagination')
        rows.extend(result['clients'])
        if len(rows) > MAX_ROWS:
            raise ValueError('Online snapshot limit exceeded')
        if page >= result['last_page']:
            # Never publish a partial list or infer unique MAC matches from it.
            if len(rows) != result['total']:
                raise ValueError('Online sessions changed during collection')
            return {'clients': rows, 'matches': username_map(rows),
                    'fetched_at': now().isoformat(), 'collected': time.monotonic()}
    raise ValueError('Incomplete online snapshot')


class OnlineSessions:
    def __init__(self):
        self.lock = threading.RLock()
        self.pool = None
        self.stopped = threading.Event()
        self.entries = OrderedDict()
        self.tasks = {}
        self.retry_at = {}
        self.errors = set()
        self.last_account = ''

    @property
    def running(self):
        return self.pool is not None

    def start(self):
        with self.lock:
            if self.pool is None:
                self.stopped = threading.Event()
                self.pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix='online-sessions')

    def stop(self):
        with self.lock:
            self.stopped.set()
            if self.pool:
                self.pool.shutdown(wait=False, cancel_futures=True)
            self.pool = None
            self.entries.clear()
            self.tasks.clear()
            self.retry_at.clear()
            self.errors.clear()

    def refresh_accounts(self):
        if not self.running:
            return
        with SessionLocal() as db:
            accounts = []
            for user, connection in db.execute(select(User, SAS4UserConnection).join(
                    SAS4UserConnection, SAS4UserConnection.user_id == User.id).where(User.active.is_(True))):
                try:
                    allowed(user)
                    accounts.append((connection_key(user, connection), connection.username, connection.encrypted_password))
                except Exception:
                    continue
        keys = {key for key, _, _ in accounts}
        with self.lock:
            if not self.running:
                return
            clock = time.monotonic()
            for key in list(self.entries):
                if key not in keys or clock - self.entries[key]['collected'] > MAX_AGE:
                    del self.entries[key]
            self.retry_at = {key: value for key, value in self.retry_at.items() if key in keys}
            self.errors.intersection_update(keys)
            for key, task in list(self.tasks.items()):
                if not task.done():
                    continue
                del self.tasks[key]
                if key not in keys:
                    continue
                try:
                    snapshot = task.result()
                    self.entries[key] = snapshot
                    self.entries.move_to_end(key)
                    while len(self.entries) > 64:
                        self.entries.popitem(last=False)
                    self.errors.discard(key)
                    self.retry_at[key] = clock + REFRESH_SECONDS
                except Exception:
                    self.errors.add(key)
                    self.retry_at[key] = clock + 60
            accounts.sort(key=lambda row: (row[0][0] <= self.last_account, row[0][0]))
            for key, username, encrypted in accounts:
                if len(self.tasks) >= 2:
                    break
                if key in self.tasks or self.retry_at.get(key, 0) > clock:
                    continue
                self.last_account = key[0]
                try:
                    password = cipher().decrypt(encrypted.encode()).decode()
                    self.tasks[key] = self.pool.submit(collect, SimpleNamespace(username=username), password, self.stopped)
                except Exception:
                    self.errors.add(key)
                    self.retry_at[key] = clock + 60

    def snapshot(self, db, user):
        # Recheck permissions and saved credentials on every read, including in-flight changes.
        allowed(user)
        connection = db.get(SAS4UserConnection, user.id)
        if not user.active or not connection:
            return None
        key = connection_key(user, connection)
        with self.lock:
            entry = self.entries.get(key)
            if entry is None or time.monotonic() - entry['collected'] > MAX_AGE:
                return None
            result = deepcopy(entry)
            result['collection_status'] = ('stale' if key in self.errors or
                time.monotonic() - entry['collected'] > REFRESH_SECONDS + 15 else 'available')
            return result

    def page(self, db, user, page=1, search='', count=7):
        snapshot = self.snapshot(db, user)
        if snapshot is None:
            connection = db.get(SAS4UserConnection, user.id)
            with self.lock:
                failed = connection and connection_key(user, connection) in self.errors
            return {'clients': [], 'total': None, 'page': page, 'per_page': count, 'last_page': 1,
                    'collection_status': 'unavailable' if failed else 'warming', 'fetched_at': None}
        term = search.strip().casefold()
        rows = [row for row in snapshot['clients'] if not term or any(term in str(row.get(field) or '').casefold()
                for field in ('username', 'name', 'ip_address', 'mac_address', 'profile', 'manager', 'nas'))]
        return {'clients': rows[(page - 1) * count:page * count], 'total': len(rows), 'page': page,
                'per_page': count, 'last_page': max(1, math.ceil(len(rows) / count)),
                'collection_status': snapshot['collection_status'], 'fetched_at': snapshot['fetched_at']}


service = OnlineSessions()
