"""Account-scoped SAS4 dashboard snapshots collected without browser requests."""
import time
from .online_sessions import OnlineSessions, connection_key
from .models import SAS4UserConnection, now


class DashboardSnapshots(OnlineSessions):
    def authorize(self, user):
        from . import sas4, section_access
        sas4.sas4_access(user)
        # NOC-only staff need the online count, but never receive dashboard
        # finance fields: the HTTP endpoints enforce their own separate scopes.
        section_access.require_any(user, ('isp_card', 'noc'))

    def collect_data(self, connection, password, stopped):
        from . import sas4
        if stopped.is_set():
            raise RuntimeError('Collection stopped')
        data = sas4.fetch_dashboard(connection, password)
        return {'data': data, 'fetched_at': now().isoformat(), 'collected': time.monotonic()}

    def read(self, db, user):
        snapshot = self.snapshot(db, user)
        if snapshot:
            return {**snapshot['data'], 'fetched_at': snapshot['fetched_at'],
                    'collection_status': snapshot['collection_status']}
        connection = db.get(SAS4UserConnection, user.id)
        with self.lock:
            failed = connection and connection_key(user, connection) in self.errors
        return {**{key: None for key in ('total_users', 'active_users', 'online_users', 'expired_users',
                                         'about_to_expire', 'balance', 'reward_points')},
                'warnings': [], 'fetched_at': None,
                'collection_status': 'unavailable' if failed else 'warming'}


service = DashboardSnapshots()
