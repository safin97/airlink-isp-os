"""Direct SAS4 card-series management using the signed-in owner's connection.

Routes and permissions follow SAS4's cards/index and cards/list UI.
Local saved FIB PIN inventory is intentionally independent of remote series.
"""
import math
from datetime import date
from typing import Literal, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator
from . import sas4, sas4_reports
from .db import get_db
from .models import audit
from .security import owner

router = APIRouter(prefix='/radius', tags=['SAS4 cards'])
PERMISSIONS = {
    'cards': 'prm_cards_download',
    'suspend': 'prm_cards_suspend_release',
    'release': 'prm_cards_suspend_release',
    'owner': 'prm_cards_change_owner',
    'expiry': 'prm_managers_sysadmin',
    'delete': 'prm_cards_delete',
}
SERIES_PATTERN = r'^[A-Za-z0-9_-]+$'


def allowed(permissions, action):
    return 'prm_managers_sysadmin' in permissions or PERMISSIONS[action] in permissions


def require(permissions, permission):
    if 'prm_managers_sysadmin' not in permissions and permission not in permissions:
        raise HTTPException(403, 'Your SAS4 account does not have permission for this card operation.')


def paginated(result, fields, page):
    rows = result.get('data')
    if not isinstance(rows, list) or len(rows) > 100 or any(not isinstance(row, dict) for row in rows):
        raise sas4.SAS4Error('SAS4 returned an invalid card list.')
    try:
        total = int(result['total'])
        current = int(result.get('current_page', page))
        size = int(result.get('per_page', 25))
        if total < 0 or current < 1 or not 1 <= size <= 100:
            raise ValueError()
    except (KeyError, ValueError, TypeError) as exc:
        raise sas4.SAS4Error('SAS4 returned invalid card pagination.') from exc
    return {'columns': [{'key': key, 'label': label} for key, label in fields],
            'rows': [{key: sas4_reports.cell(row, key) for key, _ in fields} for row in rows],
            'page': current, 'total': total, 'last_page': max(1, math.ceil(total / size))}


@router.get('')
def series(response: Response, page: int = Query(1, ge=1), search: str = Query('', max_length=200),
           manager_id: int = Query(-1, ge=-1), user=Depends(owner), db=Depends(get_db)):
    response.headers['Cache-Control'] = 'no-store'
    connection, password = sas4.local_user_connection(db, user)
    try:
        with sas4.sas4_session(connection, password) as (client, headers):
            permissions = sas4.user_permissions(client, headers)
            require(permissions, 'prm_cards_index')
            data = sas4.response_json(client.post(sas4.DEFAULT_SERVER + sas4.API_PATH + 'index/series',
                headers=headers, json=sas4.wire_payload({'page': page, 'count': 25, 'sortBy': 'series_date',
                    'direction': 'desc', 'search': search, 'parent_id': manager_id, 'type': -1, 'profile_id': -1})))
        result = paginated(data, sas4_reports.REPORTS['system-cards'][3], page)
        result['actions'] = {action: allowed(permissions, action) for action in PERMISSIONS}
        return result
    except sas4.SAS4Error as exc:
        raise HTTPException(502, str(exc)) from exc


@router.get('/cards')
def cards(response: Response, series: str = Query(..., min_length=1, max_length=128, pattern=SERIES_PATTERN),
          page: int = Query(1, ge=1), search: str = Query('', max_length=200), reveal: bool = False,
          user=Depends(owner), db=Depends(get_db)):
    response.headers['Cache-Control'] = 'no-store'
    connection, password = sas4.local_user_connection(db, user)
    try:
        with sas4.sas4_session(connection, password) as (client, headers):
            permissions = sas4.user_permissions(client, headers)
            require(permissions, 'prm_cards_index')
            require(permissions, 'prm_cards_download')
            data = sas4.response_json(client.post(sas4.DEFAULT_SERVER + sas4.API_PATH + 'index/card/' + series,
                headers=headers, json=sas4.wire_payload({'page': page, 'count': 25, 'sortBy': 'id',
                    'direction': 'asc', 'search': search, 'used_by': -1})))
        fields = [('id', 'ID'), ('serialnumber', 'Serial number'), ('username', 'Username'),
                  ('used_at', 'Used at'), ('user_details.username', 'Used by user'),
                  ('manager_details.username', 'Used by manager')]
        if reveal:
            fields.extend([('pin', 'PIN'), ('password', 'Password')])
            audit(db, user, 'sas4_cards.reveal', series)
            db.commit()
        return paginated(data, fields, page)
    except sas4.SAS4Error as exc:
        raise HTTPException(502, str(exc)) from exc


class SeriesAction(BaseModel):
    model_config = ConfigDict(extra='forbid')
    series: str = Field(min_length=1, max_length=128, pattern=SERIES_PATTERN)
    action: Literal['suspend', 'release', 'owner', 'expiry', 'delete']
    owner_id: Optional[int] = Field(default=None, ge=1)
    expiration: Optional[date] = None

    @model_validator(mode='after')
    def required_values(self):
        if (self.action == 'owner') != (self.owner_id is not None):
            raise ValueError('Select an owner only for the change-owner action')
        if (self.action == 'expiry') != (self.expiration is not None):
            raise ValueError('Select an expiry date only for the change-expiry action')
        return self


@router.post('/action')
def action(data: SeriesAction, user=Depends(owner), db=Depends(get_db)):
    connection, password = sas4.local_user_connection(db, user)
    try:
        with sas4.sas4_session(connection, password) as (client, headers):
            permissions = sas4.user_permissions(client, headers)
            require(permissions, 'prm_cards_index')
            require(permissions, PERMISSIONS[data.action])
            # Persist intent before the network mutation; never retry an uncertain result.
            audit(db, user, 'sas4_cards.' + data.action + '.requested', data.series)
            db.commit()
            base = sas4.DEFAULT_SERVER + sas4.API_PATH + 'series/'
            if data.action == 'owner':
                remote = client.post(base + 'changeOwner', headers=headers,
                    json=sas4.wire_payload({'series': [data.series], 'owner': data.owner_id}))
            elif data.action == 'expiry':
                remote = client.post(base + 'changeExpiry', headers=headers,
                    json=sas4.wire_payload({'series': [data.series], 'new_expiry': data.expiration.isoformat()}))
            else:
                # SAS4 exposes these mutations as GET. AirLink exposes POST only.
                remote = client.get(base + data.action + '/' + data.series, headers=headers)
            result = sas4.response_json(remote)
            if result.get('status') not in (200, '200'):
                raise sas4.SAS4Error('SAS4 did not confirm this change.')
        audit(db, user, 'sas4_cards.' + data.action + '.completed', data.series)
        db.commit()
        return {'ok': True}
    except sas4.SAS4Error as exc:
        raise HTTPException(502, 'The change was not confirmed. Refresh the SAS4 series before trying again.') from exc
