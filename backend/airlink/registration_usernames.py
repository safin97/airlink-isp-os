"""Account-scoped active-session MAC lookup; bounded and off the request thread."""
import hashlib
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

from fastapi import HTTPException
from . import sas4, section_access
from .sas4 import fetch_clients
from .models import SAS4UserConnection
from .security import cipher
from .wireless_clients import username_map


def fetch(connection, password):
    rows = []
    deadline = time.monotonic() + 20
    for page in range(1, 21):
        if time.monotonic() > deadline:
            return {}, 'unavailable', time.monotonic()
        result = fetch_clients(connection, password, page=page, count=500, online=True)
        if result['page'] != page:
            return {}, 'unavailable', time.monotonic()
        rows.extend(result['clients'])
        if page >= result['last_page']:
            return username_map(rows), 'available', time.monotonic()
    # Never declare a unique match from a truncated session list.
    return {}, 'unavailable', time.monotonic()


class UsernameLookup:
    def __init__(self):
        self.lock = threading.Lock()
        self.pool = None
        self.entries = {}

    def stop(self):
        with self.lock:
            if self.pool:
                self.pool.shutdown(wait=False, cancel_futures=True)
            self.pool = None
            self.entries.clear()

    def lookup(self, db, user):
        try:
            sas4.sas4_access(user)
            section_access.require_any(user, ('isp_card',), db)
        except HTTPException:
            return {}, 'not_configured'
        connection = db.get(SAS4UserConnection, user.id)
        if not connection:
            return {}, 'not_configured'
        from .online_sessions import service as sessions
        if sessions.running:
            snapshot = sessions.snapshot(db, user)
            if snapshot is None:
                status = sessions.page(db, user)['collection_status']
                return {}, 'unavailable' if status == 'unavailable' else 'pending'
            # Never present an expired session-to-MAC association as a current username.
            if snapshot['collection_status'] != 'available':
                return {}, 'unavailable'
            return snapshot['matches'], 'available'
        key = (user.id, hashlib.sha256((connection.username + '\0' + connection.encrypted_password).encode()).hexdigest())
        with self.lock:
            clock = time.monotonic()
            for old in list(self.entries):
                entry = self.entries[old]
                if entry[0].done() and clock - entry[1] > 60:
                    del self.entries[old]
            entry = self.entries.get(key)
            if entry and not entry[0].done():
                return {}, 'pending'
            if entry:
                try:
                    matches, status, fetched = entry[0].result()
                except Exception:
                    matches, status, fetched = {}, 'unavailable', entry[1]
                if clock - fetched < 30:
                    return matches, status
                del self.entries[key]
            if len(self.entries) >= 64 or sum(not e[0].done() for e in self.entries.values()) >= 2:
                return {}, 'pending'
            try:
                password = cipher().decrypt(connection.encrypted_password.encode()).decode()
            except Exception:
                return {}, 'unavailable'
            if self.pool is None:
                self.pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix='registration-usernames')
            task = self.pool.submit(fetch, SimpleNamespace(username=connection.username), password)
            self.entries[key] = (task, clock)
            return {}, 'pending'


service = UsernameLookup()
