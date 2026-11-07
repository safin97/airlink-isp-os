"""Read-only, paginated SAS4 financial reports using each account's saved connection."""
import math
from datetime import date
from typing import Optional, Literal
from cryptography.fernet import InvalidToken
from fastapi import APIRouter, Depends, HTTPException, Query
from . import sas4
from .db import get_db
from .models import SAS4UserConnection
from .security import cipher

router = APIRouter(prefix='/api/integrations/sas4/reports', tags=['SAS4 reports'])
# Routes and fields verified against the SAS4 report UI and read-only API responses.
REPORTS = {
    'activations': ('Activations', 'index/activations', 'id', [
        ('created_at', 'Date'), ('user_details.username', 'Username'),
        ('manager_details.username', 'Manager'), ('profile_details.name', 'Service profile'),
        ('total_price', 'Total price'), ('activation_method', 'Method'),
        ('old_expiration', 'Previous expiry'), ('new_expiration', 'New expiry'), ('refunded', 'Refunded')]),
    'activation-statistics': ('Activation statistics', 'report/activations', 'day', []),
    'money-transfers': ('Money Transfers', 'report/depodrawal', 'created_at', [
        ('created_at', 'Date'), ('operation', 'Operation'), ('cr_manager', 'Credit manager'),
        ('dr_manager', 'Debit manager'), ('amount', 'Amount'), ('comment', 'Comment')]),
}


def catalog():
    return [{'id': key, 'name': spec[0]} for key, spec in REPORTS.items()]


def cell(row, path):
    value = row
    for key in path.split('.'):
        value = value.get(key) if isinstance(value, dict) else None
    if value is None or isinstance(value, (str, int, float, bool)):
        return value[:2000] if isinstance(value, str) else value
    return None


def fetch_report(connection, password, report, page=1, search='', date_start=None, date_end=None, operation='deposit', period='daily', year=None, month=None, transport=None, manager_id=-1):
    title, route, sort, fields = REPORTS[report]
    if report == 'activation-statistics':
        return fetch_statistics(connection, password, period, year, month, page, transport, manager_id)
    payload = {'page': page, 'count': 25, 'sortBy': sort, 'direction': 'desc', 'search': search, 'manager_id': manager_id}
    if report == 'money-transfers':
        payload.update(operation=operation)
    if date_start:
        payload['date_start'] = date_start.isoformat()
    if date_end:
        payload['date_end'] = date_end.isoformat()
    with sas4.sas4_session(connection, password, transport) as (client, headers):
        result = sas4.response_json(client.post(sas4.DEFAULT_SERVER + sas4.API_PATH + route,
                                               headers=headers, json=sas4.wire_payload(payload)))
    rows = result.get('data')
    if not isinstance(rows, list) or len(rows) > 100 or any(not isinstance(row, dict) for row in rows):
        raise sas4.SAS4Error('SAS4 returned an invalid report.')
    try:
        total = int(result['total'])
        current = int(result.get('current_page', page))
        per_page = int(result.get('per_page', 25))
        if total < 0 or current < 1 or not 1 <= per_page <= 100:
            raise ValueError()
    except (KeyError, ValueError, TypeError) as exc:
        raise sas4.SAS4Error('SAS4 returned invalid report pagination.') from exc
    # Never return raw nested SAS4 records, card PINs or API credentials.
    return {'report': report, 'title': title,
            'columns': [{'key': key, 'label': label} for key, label in fields],
            'rows': [{key: cell(row, key) for key, _ in fields} for row in rows],
            'page': current, 'total': total, 'last_page': max(1, math.ceil(total / per_page)), 'per_page': per_page}



def fetch_statistics(connection, password, period, year, month, page=1, transport=None, manager_id=-1):
    today = date.today()
    year, month = year or today.year, month or today.month
    payload = {'type': period, 'year': year, 'month': month, 'manager_id': manager_id,
               'sub_managers': 'true', 'activation_method': 'any'}
    with sas4.sas4_session(connection, password, transport) as (client, headers):
        result = sas4.response_json(client.post(sas4.DEFAULT_SERVER + sas4.API_PATH + 'report/activations',
                                               headers=headers, json=sas4.wire_payload(payload)))
    data, profiles = result.get('data'), result.get('profiles')
    if not isinstance(data, list) or not isinstance(profiles, list) or len(data) > 50000:
        raise sas4.SAS4Error('SAS4 returned invalid activation statistics.')
    names = {str(p['id']): cell(p, 'name') for p in profiles if isinstance(p, dict) and 'id' in p}
    key = 'day' if period == 'daily' else 'month'
    rows = []
    for row in data:
        if not isinstance(row, dict):
            raise sas4.SAS4Error('SAS4 returned invalid activation statistics.')
        bucket, total = sas4.summary_number(row.get(key)), sas4.summary_number(row.get('total'))
        if total is None or (row.get(key) is not None and
                (bucket is None or not 1 <= bucket <= (31 if key == 'day' else 12))):
            raise sas4.SAS4Error('SAS4 returned invalid activation counts.')
        # Monthly SAS4 responses cover the whole year, including annual rollups.
        if period == 'monthly' and bucket != month:
            continue
        profile = row.get('profile_id')
        # SAS4 includes SQL rollup rows with a null day/month: retain them as totals.
        label = 'Total' if bucket is None else (f'{year:04d}-{month:02d}-{bucket:02d}' if key == 'day' else f'{year:04d}-{bucket:02d}')
        rows.append({'period': label,
                     'profile': 'Total' if profile is None else names.get(str(profile), str(profile)), 'activations': total})
    rows.sort(key=lambda r: (r['period'], r['profile'] or ''))
    return {'report': 'activation-statistics', 'title': 'Activation statistics',
            'columns': [{'key': 'period', 'label': 'Date'}, {'key': 'profile', 'label': 'Service profile'},
                        {'key': 'activations', 'label': 'Activations'}],
            'rows': rows[(page - 1) * 25:page * 25], 'page': page, 'total': len(rows),
            'last_page': max(1, math.ceil(len(rows) / 25)), 'per_page': 25,
            'year': year, 'month': month, 'period': period}


@router.get('')
def report_catalog(user=Depends(sas4.sas4_access)):
    return catalog()


def fetch_managers(connection, password, transport=None):
    with sas4.sas4_session(connection, password, transport) as (client, headers):
        result = sas4.response_json(client.get(sas4.DEFAULT_SERVER + sas4.API_PATH + 'index/manager', headers=headers))
    rows = result.get('data')
    if not isinstance(rows, list):
        raise sas4.SAS4Error('SAS4 manager list is unavailable.')
    managers = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        manager_id = sas4.summary_number(row.get('id'))
        username = row.get('username')
        if manager_id and isinstance(username, str) and username:
            managers[manager_id] = {'id': manager_id, 'username': username[:128]}
    return sorted(managers.values(), key=lambda row: row['username'].casefold())


@router.get('/managers')
def read_managers(user=Depends(sas4.sas4_access), db=Depends(get_db)):
    connection = db.get(SAS4UserConnection, user.id)
    if not connection:
        raise HTTPException(409, 'Set up SAS4 connection below Settings before choosing a manager')
    try:
        password = cipher().decrypt(connection.encrypted_password.encode()).decode()
        return fetch_managers(connection, password)
    except InvalidToken as exc:
        raise HTTPException(503, 'Save your SAS4 password again in SAS4 connection below Settings') from exc
    except sas4.SAS4Error as exc:
        raise HTTPException(502, str(exc)) from exc


@router.get('/{report}')
def read_report(report: str, page: int = Query(1, ge=1, le=1000000),
                search: str = Query('', max_length=200), date_start: Optional[date] = None,
                date_end: Optional[date] = None, operation: Literal['deposit', 'withdrawal'] = 'deposit',
                period: Literal['daily', 'monthly'] = 'daily', year: Optional[int] = Query(None, ge=2017, le=2100),
                month: Optional[int] = Query(None, ge=1, le=12), manager_id: int = Query(-1, ge=-1), user=Depends(sas4.sas4_access), db=Depends(get_db)):
    if manager_id == 0:
        raise HTTPException(422, 'Choose a valid SAS4 manager')
    if report not in REPORTS:
        raise HTTPException(404, 'Unknown SAS4 report')
    if date_start and date_end and date_start > date_end:
        raise HTTPException(422, 'From date must be before or equal to To date')
    connection = db.get(SAS4UserConnection, user.id)
    if not connection:
        raise HTTPException(409, 'Set up SAS4 connection below Settings to view reports')
    try:
        password = cipher().decrypt(connection.encrypted_password.encode()).decode()
        return fetch_report(connection, password, report, page, search, date_start, date_end, operation, period, year, month, manager_id=manager_id)
    except InvalidToken as exc:
        raise HTTPException(503, 'Save your SAS4 password again in SAS4 connection below Settings') from exc
    except sas4.SAS4Error as exc:
        raise HTTPException(502, str(exc)) from exc
