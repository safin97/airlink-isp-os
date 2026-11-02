"""SAS4 integration using the vendor's published encrypted API protocol.
Protocol reference: https://github.com/SnonoSystems/cryptojs_aes_python
Profile edits and card recharge occur only through explicit, permission-checked requests.
"""
from . import section_access
import base64
import hashlib
import json
import math
import os
from typing import Optional, Union, Literal
from contextlib import contextmanager
import httpx
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.fernet import InvalidToken
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from .db import get_db
from .models import SAS4UserConnection, CustomerProbeSettings, now, audit
from .security import cipher, current_user
from .client_telemetry import attach_telemetry
from .customer_probes import configuration as probe_configuration, service as customer_probe_service

router = APIRouter(prefix='/api/integrations/sas4', tags=['SAS4'])
DEFAULT_SERVER = 'http://airlinkcom.online'
API_PATH = '/admin/api/index.php/api/'
# Public SAS4 wire-protocol constant, not an account credential.
WIRE_PASSPHRASE = b'abcdefghijuklmno0123456789012345'


class ConnectionInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    username: str = Field(min_length=1, max_length=128)
    password: Optional[str] = Field(default=None, max_length=1024)

    @field_validator('username')
    @classmethod
    def valid_username(cls, value):
        value = value.strip()
        if not value:
            raise ValueError('SAS4 username is required')
        return value


def wire_payload(data):
    """CryptoJS/OpenSSL salted AES-256-CBC envelope required by SAS4."""
    salt = os.urandom(8)
    material = previous = b''
    while len(material) < 48:
        previous = hashlib.md5(previous + WIRE_PASSPHRASE + salt).digest()
        material += previous
    padder = padding.PKCS7(128).padder()
    encoded = json.dumps(data, ensure_ascii=True, separators=(',', ':')).encode('utf-8')
    padded = padder.update(encoded) + padder.finalize()
    encryptor = Cipher(algorithms.AES(material[:32]), modes.CBC(material[32:48])).encryptor()
    encrypted = encryptor.update(padded) + encryptor.finalize()
    return {'payload': base64.b64encode(b'Salted__' + salt + encrypted).decode('ascii')}


class SAS4Error(Exception):
    pass


def response_json(response, login=False):
    if response.status_code in (401, 403):
        raise SAS4Error('SAS4 rejected access. Check the API account credentials and user-list permission.')
    if not 200 <= response.status_code < 300:
        raise SAS4Error(f'SAS4 returned HTTP {response.status_code}. Check the server URL and API availability.')
    if len(response.content) > 8 * 1024 * 1024:
        raise SAS4Error('SAS4 response was too large. Reduce the client page size.')
    try:
        data = response.json()
    except ValueError as exc:
        raise SAS4Error('SAS4 did not return JSON. Check the server URL and API availability.') from exc
    if not isinstance(data, dict):
        raise SAS4Error('SAS4 returned an unexpected response format.')
    if data.get('status') in (False, 401, 403, '401', '403') or data.get('error'):
        raise SAS4Error('SAS4 rejected the request. Check the credentials and account permissions.')
    return data


def flag(value):
    if value in (True, 1, '1', 'true'):
        return True
    if value in (False, 0, '0', 'false'):
        return False
    return None


def user_status(service, enabled, online):
    active = flag(service.get('status')) if isinstance(service, dict) else flag(service)
    valid_expiry = flag(service.get('expiration')) if isinstance(service, dict) else None
    if enabled is False:
        status = 'disabled'
    elif valid_expiry is False:
        status = 'expired'
    elif active is True:
        status = 'active'
    elif active is False:
        status = 'limited' if valid_expiry is True else 'expired / limited'
    else:
        status = 'unknown'
    if online is True:
        return 'online' if status == 'unknown' else status + ' • online'
    return status


def client_record(row):
    if not isinstance(row, dict) or not isinstance(row.get('username'), str):
        raise SAS4Error('SAS4 returned an invalid client record.')
    enabled = flag(row.get('enabled'))
    online = flag(row.get('online_status'))
    service = row.get('status')
    status = user_status(service, enabled, online)
    profile = row.get('profile_details')
    # Explicit allow-list: SAS4 passwords, balances and other private fields never leave this adapter.
    return {'id': row.get('id'), 'username': row['username'],
            'name': ' '.join(str(row.get(k) or '') for k in ('firstname', 'lastname')).strip(),
            'profile': profile.get('name') if isinstance(profile, dict) else None,
            'status': status, 'online': online, 'enabled': enabled,
            'ip_address': row.get('static_ip'), 'expiration': row.get('expiration'),
            'manager': row.get('parent_username'), 'last_online': row.get('last_online')}


@contextmanager
def sas4_session(connection, password, transport=None):
    try:
        with httpx.Client(timeout=httpx.Timeout(15, connect=5), follow_redirects=False,
                          trust_env=False, transport=transport) as client:
            login = response_json(client.post(DEFAULT_SERVER + API_PATH + 'login', json=wire_payload({
                'username': connection.username, 'password': password})), login=True)
            token = login.get('token')
            if not isinstance(token, str) or not token or len(token) > 16384:
                raise SAS4Error('SAS4 login did not return a token. Check the API username and password.')
            yield client, {'Authorization': 'Bearer ' + token}
    except httpx.TimeoutException as exc:
        raise SAS4Error('SAS4 timed out. Check connectivity from the AirLink server.') from exc
    except httpx.HTTPError as exc:
        raise SAS4Error('Could not connect to SAS4. Check the URL, network and TLS certificate.') from exc


def online_record(row):
    if not isinstance(row, dict) or not isinstance(row.get('username'), str):
        raise SAS4Error('SAS4 returned an invalid online-user record.')
    details = row.get('user_details')
    details = details if isinstance(details, dict) else {}
    nas = row.get('nas_details')
    return {'id': details.get('id'), 'session_id': row.get('radacctid'),
            'username': row['username'],
            'name': ' '.join(str(details.get(k) or '') for k in ('firstname', 'lastname')).strip(),
            'profile': row.get('user_profile_name'),
            'status': user_status(row.get('status', details.get('status')), flag(details.get('enabled', row.get('enabled'))), True),
            'online': True,
            'ip_address': row.get('framedipaddress'), 'expiration': details.get('expiration'),
            'manager': row.get('parent_username'), 'mac_address': row.get('callingstationid'),
            'nas': nas.get('shortname') if isinstance(nas, dict) else None}


def fetch_clients(connection, password, page=1, search='', count=7, transport=None, online=False):
    route = 'index/online' if online else 'index/user'
    with sas4_session(connection, password, transport) as (client, headers):
        result = response_json(client.post(DEFAULT_SERVER + API_PATH + route, headers=headers,
            json=wire_payload({'page': page, 'count': count, 'sortBy': 'username',
                               'direction': 'asc', 'search': search})))
    rows = result.get('data')
    if not isinstance(rows, list) or len(rows) > 500:
        raise SAS4Error('SAS4 returned an unexpected client list.')
    try:
        total = int(result['total'])
        current = int(result.get('current_page', page))
        per_page = int(result.get('per_page', count))
        if total < 0 or current < 1 or per_page < 1:
            raise ValueError()
    except (KeyError, ValueError, TypeError) as exc:
        raise SAS4Error('SAS4 returned invalid pagination information.') from exc
    return {'clients': [(online_record if online else client_record)(row) for row in rows], 'total': total, 'page': current,
            'per_page': per_page, 'last_page': max(1, math.ceil(total / per_page)),
            'fetched_at': now().isoformat()}


def summary_number(value):
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int) and value >= 0:
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def fetch_dashboard(connection, password, transport=None):
    sections = {}
    warnings = []
    with sas4_session(connection, password, transport) as (client, headers):
        for name in ('subscribers', 'finance'):
            try:
                response = response_json(client.get(DEFAULT_SERVER + API_PATH + 'advancedDashboard/' + name, headers=headers))
                data = response.get('data')
                if not isinstance(data, dict) or response.get('status') not in (200, '200'):
                    raise SAS4Error('SAS4 returned an unexpected dashboard response.')
                sections[name] = data
            except (SAS4Error, httpx.HTTPError):
                warnings.append(f'SAS4 {name} data is unavailable. Check account permissions or try again.')
    if not sections:
        raise SAS4Error('SAS4 dashboard data is unavailable. Check account permissions or try again.')
    subscribers = sections.get('subscribers', {})
    finance = sections.get('finance', {})
    balance = finance.get('balance')
    if isinstance(balance, bool) or not isinstance(balance, (int, float, str)):
        balance = None
    elif len(str(balance)) > 100:
        balance = None
    return {'total_users': summary_number(subscribers.get('total')),
            'active_users': summary_number(subscribers.get('active')),
            'online_users': summary_number(subscribers.get('online')),
            'expired_users': summary_number(subscribers.get('expired')),
            'about_to_expire': summary_number(subscribers.get('expiring_soon')),
            'balance': balance, 'reward_points': summary_number(finance.get('reward_points')),
            'warnings': warnings, 'fetched_at': now().isoformat()}


def connection_status(connection):
    return {'server_url': DEFAULT_SERVER,
            'username': connection.username if connection else '',
            'configured': bool(connection and connection.encrypted_password),
            'has_password': bool(connection and connection.encrypted_password)}


def sas4_access(user=Depends(current_user)):
    if user.role not in ('owner', 'manager') and section_access.role_policy(user) is None:
        raise HTTPException(403, 'Manager access is required for SAS4 clients')
    return user


class ProbeSettingsInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    enabled: bool = True
    community: Optional[str] = Field(default=None, max_length=255)
    api_username: str = Field(default='', max_length=128)
    api_password: Optional[str] = Field(default=None, max_length=1024)
    verify_tls: bool = True
    allow_http: bool = False
    try_public_snmp: bool = True


def public_probe_settings(config):
    return {key: config[key] for key in ('enabled', 'api_username', 'verify_tls', 'allow_http', 'try_public_snmp')} | {
        'has_community': bool(config['community']), 'has_api_password': bool(config['api_password']),
        'saved_snmp_profiles': config['configured_snmp_count']}


@router.get('/device-access')
def get_probe_settings(user=Depends(sas4_access), db=Depends(get_db)):
    return public_probe_settings(probe_configuration(db, user))


@router.put('/device-access')
def save_probe_settings(data: ProbeSettingsInput, user=Depends(sas4_access), db=Depends(get_db)):
    config = probe_configuration(db, user)
    if data.api_username and data.api_username != config['api_username'] and not data.api_password:
        raise HTTPException(422, 'Enter the device API password when changing the username')
    if data.community is not None and data.community and not data.community.strip():
        raise HTTPException(422, 'Enter a valid SNMP community')
    for key in ('enabled', 'api_username', 'verify_tls', 'allow_http', 'try_public_snmp'):
        config[key] = getattr(data, key)
    if data.community is not None:
        config['community'] = data.community
    if data.api_password:
        config['api_password'] = data.api_password
    if not data.api_username:
        config['api_password'] = ''
    config.pop('snmp_candidates', None)
    config.pop('configured_snmp_count', None)
    obj = db.get(CustomerProbeSettings, user.id)
    if obj is None:
        obj = CustomerProbeSettings(user_id=user.id)
        db.add(obj)
    obj.encrypted_settings = cipher().encrypt(json.dumps(config).encode()).decode()
    obj.updated_at = now()
    audit(db, user, 'customer_probe.configure', user.id)
    db.commit()
    return public_probe_settings(probe_configuration(db, user))


@router.get('')
def get_connection(user=Depends(sas4_access), db=Depends(get_db)):
    return connection_status(db.get(SAS4UserConnection, user.id))


@router.put('')
def save_connection(data: ConnectionInput, user=Depends(sas4_access), db=Depends(get_db)):
    connection = db.get(SAS4UserConnection, user.id)
    if not data.password and (not connection or connection.username != data.username):
        raise HTTPException(422, 'Enter the SAS4 password when adding a connection or changing its username')
    if connection is None:
        connection = SAS4UserConnection(user_id=user.id)
        db.add(connection)
    connection.username = data.username
    if data.password:
        connection.encrypted_password = cipher().encrypt(data.password.encode()).decode()
    connection.updated_at = now()
    audit(db, user, 'sas4.configure', 'sas4')
    db.commit()
    return connection_status(connection)


@router.get('/clients')
def get_clients(page: int = Query(1, ge=1, le=1000000), search: str = Query('', max_length=200),
                user=Depends(sas4_access), db=Depends(get_db)):
    connection = db.get(SAS4UserConnection, user.id)
    if not connection:
        raise HTTPException(409, 'Configure the SAS4 connection first')
    try:
        password = cipher().decrypt(connection.encrypted_password.encode()).decode()
        return fetch_clients(connection, password, page, search)
    except InvalidToken as exc:
        raise HTTPException(503, 'SAS4 credentials cannot be decrypted. Save the password again.') from exc
    except SAS4Error as exc:
        raise HTTPException(502, str(exc)) from exc


@router.get('/dashboard')
def get_dashboard(user=Depends(sas4_access), db=Depends(get_db)):
    connection = db.get(SAS4UserConnection, user.id)
    if not connection:
        raise HTTPException(409, 'Configure the SAS4 connection first')
    try:
        password = cipher().decrypt(connection.encrypted_password.encode()).decode()
        return fetch_dashboard(connection, password)
    except InvalidToken as exc:
        raise HTTPException(503, 'SAS4 credentials cannot be decrypted. Save the password again.') from exc
    except SAS4Error as exc:
        raise HTTPException(502, str(exc)) from exc


@router.get('/online-count')
def get_online_count(user=Depends(sas4_access), db=Depends(get_db)):
    result = get_dashboard(user, db)
    return {'online_users': result.get('online_users')}


@router.get('/online')
def get_online_users(page: int = Query(1, ge=1, le=1000000), search: str = Query('', max_length=200),
                     user=Depends(sas4_access), db=Depends(get_db)):
    connection = db.get(SAS4UserConnection, user.id)
    if not connection:
        raise HTTPException(409, 'Configure the SAS4 connection first')
    try:
        password = cipher().decrypt(connection.encrypted_password.encode()).decode()
        result = attach_telemetry(db, user, fetch_clients(connection, password, page, search, online=True))
        return customer_probe_service.enrich(db, user, result)
    except InvalidToken as exc:
        raise HTTPException(503, 'SAS4 credentials cannot be decrypted. Save the password again.') from exc
    except SAS4Error as exc:
        raise HTTPException(502, str(exc)) from exc


# Fields in SAS4's user form. Financial balances and session records are not profile settings.
USER_FIELDS = {
    'username': ('Username', 'text', 'prm_users_rename'),
    'new_password': ('Password', 'password', None),
    'firstname': ('First name', 'text', None),
    'lastname': ('Last name', 'text', None),
    'phone': ('Phone number', 'text', None),
    'expiration': ('Card expiry date', 'datetime', 'prm_users_advanced'),
    'email': ('Email', 'text', None),
    'company': ('Company', 'text', None),
    'address': ('Address', 'text', None),
    'city': ('City', 'text', None),
    'street': ('Street', 'text', None),
    'apartment': ('Apartment', 'text', None),
    'contract_id': ('Contract ID', 'text', None),
    'national_id': ('National ID', 'text', None),
    'notes': ('Notes', 'multiline', None),
    'enabled': ('Account enabled', 'switch', 'prm_users_enable_disable'),
    'profile_id': ('Service profile', 'select', 'prm_users_change_profile'),
    'parent_id': ('SAS4 manager', 'select', 'prm_users_change_parent'),
    'site_id': ('Site', 'select', 'prm_sites_management'),
    'group_id': ('Group', 'select', 'prm_groups_assign'),
    'auto_renew': ('Auto renew', 'switch', 'prm_users_auto_renew'),
    'mac_auth': ('MAC lock', 'switch', 'prm_users_mac_lock'),
    'use_separate_portal_password': ('Separate portal password', 'switch', None),
    'portal_password': ('New portal password', 'password', None),
    'simultaneous_sessions': ('Simultaneous sessions', 'number', 'prm_users_advanced'),
    'static_ip': ('Static IP', 'text', 'prm_users_advanced'),
    'mikrotik_winbox_group': ('MikroTik Winbox group', 'text', 'prm_users_advanced'),
    'mikrotik_framed_route': ('MikroTik framed route', 'text', 'prm_users_advanced'),
    'mikrotik_addresslist': ('MikroTik address list', 'text', 'prm_users_advanced'),
    'mikrotik_ipv6_prefix': ('IPv6 prefix', 'text', 'prm_users_advanced'),
    'user_type': ('User type', 'select', 'prm_users_advanced'),
    'restricted': ('Restricted', 'switch', 'prm_users_advanced'),
}
USER_OPTIONS = {
    'profile_id': ('list/profile/0', 'name'), 'parent_id': ('index/manager', 'username'),
    'site_id': ('site', 'name'), 'group_id': ('group', 'name'),
}
VISIBLE_USER_FIELDS = (
    'username', 'new_password', 'firstname', 'lastname', 'phone', 'expiration',
    'email', 'company', 'address', 'city', 'enabled', 'parent_id', 'profile_id', 'mac_auth',
)


class UserChanges(BaseModel):
    model_config = ConfigDict(extra='forbid')
    changes: dict[str, Union[str, int, bool, None]] = Field(min_length=1, max_length=40)

    @field_validator('changes')
    @classmethod
    def validate_changes(cls, changes):
        from datetime import datetime
        import ipaddress
        import re
        for key, value in changes.items():
            if key not in USER_FIELDS:
                raise ValueError('Unsupported user setting')
            kind = USER_FIELDS[key][1]
            if kind in ('text', 'password', 'datetime', 'multiline'):
                if value is not None and not isinstance(value, str):
                    raise ValueError('Text fields must contain text')
                if value is not None and len(value) > (4000 if key == 'notes' else 255):
                    raise ValueError('User setting is too long')
            if kind == 'switch' and (type(value) not in (bool, int) or value not in (0, 1)):
                raise ValueError('Invalid switch value')
            if kind in ('select', 'number') and value is not None and (type(value) is not int or value < -1):
                raise ValueError('Invalid numeric setting')
            if key in ('profile_id', 'parent_id', 'simultaneous_sessions') and (type(value) is not int or value < 1):
                raise ValueError('This setting must be a positive number')
            if key == 'user_type' and value not in (0, 1):
                raise ValueError('Invalid user type')
            if kind == 'password' and not value:
                raise ValueError('Password changes must not be empty')
            if key == 'username' and (not value or not re.fullmatch(r'[a-zA-Z.@_0-9:-]+', value)):
                raise ValueError('Invalid username')
            if key == 'expiration' and value:
                try:
                    datetime.strptime(value, '%Y-%m-%d %H:%M:%S')
                except ValueError as exc:
                    raise ValueError('Expiry must be YYYY-MM-DD HH:MM:SS in SAS4 server time') from exc
            if key == 'static_ip' and value:
                ipaddress.ip_address(value)
        return changes


def user_permissions(client, headers):
    data = response_json(client.get(DEFAULT_SERVER + API_PATH + 'auth', headers=headers))
    return set(data.get('permissions') or [])


def can_edit_user_field(key, permissions):
    admin = 'prm_managers_sysadmin' in permissions
    permission = USER_FIELDS[key][2]
    if key == 'profile_id':
        return admin or permission in permissions
    return admin or ('prm_users_update' in permissions and (permission is None or permission in permissions))


def can_change_current_profile(record, permissions):
    status = record.get('status')
    expired = isinstance(status, dict) and flag(status.get('expiration')) is False
    return (can_edit_user_field('profile_id', permissions) and
            (expired or
             bool({'prm_managers_sysadmin', 'prm_users_change_profile_active'} & permissions)))


def raw_user(client, headers, user_id):
    response = response_json(client.get(DEFAULT_SERVER + API_PATH + f'user/{user_id}', headers=headers))
    record = response.get('data')
    if response.get('status') not in (200, '200') or not isinstance(record, dict) or str(record.get('id')) != str(user_id):
        raise SAS4Error('SAS4 user is unavailable or your account cannot access it.')
    return record


def user_information(client, headers, user_id, permissions):
    record = raw_user(client, headers, user_id)
    fields = []
    for key in VISIBLE_USER_FIELDS:
        label, kind, permission = USER_FIELDS[key]
        editable = can_edit_user_field(key, permissions)
        field = {'key': key, 'label': label, 'kind': kind, 'editable': editable,
                 'value': None if kind == 'password' else record.get(key)}
        if not editable:
            field['reason'] = 'Requires SAS4 ' + (permission or 'prm_users_update') + ' permission.'
        if key == 'profile_id' and editable:
            editable = can_change_current_profile(record, permissions)
            field['editable'] = editable
            if not editable:
                field['reason'] = 'Requires SAS4 prm_users_change_profile_active permission for an active user.'
            else:
                field['help'] = 'The selected service profile takes effect when you save.'
        if kind == 'select':
            value = record.get(key)
            label_value = record.get('profile_name') if key == 'profile_id' else record.get('parent_username') if key == 'parent_id' else value
            field['options'] = [{'value': value, 'label': str(label_value or value or 'None')}]
            if key == 'user_type':
                field['options'] = [{'value': 0, 'label': 'Regular user'}, {'value': 1, 'label': 'Wireless access point'}]
            elif editable:
                route, label_key = USER_OPTIONS[key]
                try:
                    data = response_json(client.get(DEFAULT_SERVER + API_PATH + route, headers=headers)).get('data')
                    if not isinstance(data, list):
                        raise SAS4Error('SAS4 options unavailable')
                    options = [{'value': row['id'], 'label': str(row.get(label_key) or row['id'])} for row in data if isinstance(row, dict) and 'id' in row]
                    if key in ('site_id', 'group_id'):
                        options.insert(0, {'value': None, 'label': 'None'})
                    field['options'] += [o for o in options if o['value'] != value]
                except (SAS4Error, httpx.HTTPError):
                    field.update(editable=False, reason='SAS4 choices are unavailable. Reopen this user to retry.')
        fields.append(field)
    return {'id': record['id'], 'username': record.get('username'), 'fields': fields,
            'can_recharge': can_recharge(permissions),
            'status': client_record(record)['status'], 'last_online': record.get('last_online')}


def fetch_user(connection, password, user_id, transport=None):
    with sas4_session(connection, password, transport) as (client, headers):
        permissions = user_permissions(client, headers)
        return user_information(client, headers, user_id, permissions)


def update_user(connection, password, user_id, changes, transport=None):
    with sas4_session(connection, password, transport) as (client, headers):
        permissions = user_permissions(client, headers)
        if any(not can_edit_user_field(key, permissions) for key in changes):
            raise HTTPException(403, 'Your SAS4 account does not have permission to edit one or more selected fields.')
        current = raw_user(client, headers, user_id)
        if 'profile_id' in changes:
            if not can_change_current_profile(current, permissions):
                raise HTTPException(403, 'Your SAS4 account cannot change the service profile of an active user.')
            profiles = response_json(client.get(DEFAULT_SERVER + API_PATH + 'list/profile/0', headers=headers)).get('data')
            if not isinstance(profiles, list) or changes['profile_id'] not in {row.get('id') for row in profiles if isinstance(row, dict)}:
                raise HTTPException(422, 'The selected service profile is unavailable to your SAS4 account.')
        # SAS4 uses a full form update: preserve existing fields rather than blanking unrelated settings.
        payload = {key: current[key] for key in USER_FIELDS if key in current and key not in ('username', 'portal_password', 'new_password') and (can_edit_user_field(key, permissions) or key in ('profile_id', 'parent_id'))}
        normal = {key: value for key, value in changes.items() if key not in ('username', 'new_password', 'profile_id')}
        saved = []
        try:
            if normal:
                payload.update(normal)
                result = response_json(client.put(DEFAULT_SERVER + API_PATH + f'user/{user_id}', headers=headers, json=wire_payload(payload)))
                if result.get('status') not in (200, '200'):
                    raise SAS4Error('SAS4 rejected the user settings. Check the values and account permissions.')
                saved.extend(normal)
            if 'profile_id' in changes:
                result = response_json(client.post(DEFAULT_SERVER + API_PATH + 'user/changeProfile', headers=headers,
                    json=wire_payload({'user_id': user_id, 'profile_id': changes['profile_id'], 'change_type': 'immediate'})))
                if result.get('status') not in (200, '200'):
                    raise SAS4Error('SAS4 could not change this service profile. Check the account permissions.')
                saved.append('profile_id')
            if 'username' in changes:
                result = response_json(client.post(DEFAULT_SERVER + API_PATH + f'user/rename/{user_id}', headers=headers,
                    json=wire_payload({'new_username': changes['username']})))
                if result.get('status') not in (200, '200'):
                    raise SAS4Error('SAS4 could not rename this user. The username may already be used.')
                saved.append('username')
            if changes.get('new_password'):
                result = response_json(client.post(DEFAULT_SERVER + API_PATH + 'user/password', headers=headers,
                    json=wire_payload({'user_id': user_id, 'new_password': changes['new_password'], 'confirm_password': changes['new_password']})))
                if result.get('status') not in (200, '200'):
                    raise SAS4Error('SAS4 could not change this user password.')
                saved.append('new_password')
        except (SAS4Error, httpx.HTTPError) as exc:
            prefix = 'Some changes were saved. Reopen this user before retrying. ' if saved else 'Save was not confirmed. Reopen this user to check before retrying. '
            raise SAS4Error(prefix + (str(exc) if isinstance(exc, SAS4Error) else 'SAS4 connection failed.')) from exc
        return {'saved': True, 'saved_fields': saved}


def local_user_connection(db, user):
    connection = db.get(SAS4UserConnection, user.id)
    if not connection:
        raise HTTPException(409, 'Configure the SAS4 connection first')
    try:
        return connection, cipher().decrypt(connection.encrypted_password.encode()).decode()
    except InvalidToken as exc:
        raise HTTPException(503, 'SAS4 credentials cannot be decrypted. Save the password again.') from exc


@router.get('/users/{user_id}')
def get_user_information(user_id: int, user=Depends(sas4_access), db=Depends(get_db)):
    if user_id < 1:
        raise HTTPException(422, 'Invalid SAS4 user ID')
    connection, password = local_user_connection(db, user)
    try:
        return fetch_user(connection, password, user_id)
    except SAS4Error as exc:
        raise HTTPException(502, str(exc)) from exc


@router.put('/users/{user_id}')
def save_user_information(user_id: int, data: UserChanges, user=Depends(sas4_access), db=Depends(get_db)):
    if user_id < 1:
        raise HTTPException(422, 'Invalid SAS4 user ID')
    connection, password = local_user_connection(db, user)
    try:
        result = update_user(connection, password, user_id, data.changes)
        audit(db, user, 'sas4.user.update', str(user_id))
        db.commit()
        return result
    except SAS4Error as exc:
        raise HTTPException(502, str(exc)) from exc


class CardRecharge(BaseModel):
    model_config = ConfigDict(extra='forbid')
    method: Literal['card', 'credit', 'extend'] = 'card'
    pin: Optional[str] = Field(default=None, max_length=128)
    transaction_id: str = Field(pattern=r'^[a-f0-9]{32}$')
    extension_id: Optional[int] = Field(default=None, ge=1)
    expected_cost: Optional[str] = Field(default=None, max_length=40)
    expected_profile_id: Optional[int] = Field(default=None, ge=1)
    expected_expiration: Optional[str] = Field(default=None, max_length=80)

    @model_validator(mode='after')
    def valid_request(self):
        if self.method == 'card':
            self.pin = (self.pin or '').strip()
            if not self.pin or any(ord(c) < 32 for c in self.pin):
                raise ValueError('Enter the card PIN')
        else:
            if self.expected_cost is None or self.expected_profile_id is None:
                raise ValueError('Refresh the recharge price first')
            money(self.expected_cost)
        if self.method == 'extend' and self.extension_id is None:
            raise ValueError('Select an extension')
        return self


def money(value):
    from decimal import Decimal, InvalidOperation
    try:
        amount = Decimal(str(value))
        if not amount.is_finite() or amount < 0 or amount > Decimal('1000000000'):
            raise ValueError()
        return amount
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError('Invalid amount') from exc


def recharge_permissions(permissions):
    admin = 'prm_managers_sysadmin' in permissions
    activate = admin or 'prm_users_activate' in permissions
    credit = admin or 'prm_users_activate_credit' in permissions
    return {'card': admin or (activate and 'prm_users_activate_card' in permissions),
            'credit': activate and credit,
            'extend': admin or ('prm_users_extend' in permissions and credit)}


def can_recharge(permissions):
    return any(recharge_permissions(permissions).values())


def require_recharge(permissions, method):
    if not recharge_permissions(permissions).get(method):
        raise HTTPException(403, 'Your SAS4 account does not have permission for this recharge method.')


def activation_info(client, headers, user_id):
    result = response_json(client.get(DEFAULT_SERVER + API_PATH + f'user/activationData/{user_id}', headers=headers))
    if result.get('status') not in (200, '200') or not isinstance(result.get('data'), dict):
        raise SAS4Error('SAS4 activation details are unavailable.')
    return result['data']


def recharge_data(client, headers, user_id, method='card'):
    require_recharge(user_permissions(client, headers), method)
    raw_user(client, headers, user_id)
    return activation_info(client, headers, user_id)


def extension_options(client, headers, profile_id):
    result = response_json(client.get(DEFAULT_SERVER + API_PATH + f'allowedExtensions/{int(profile_id)}', headers=headers))
    if result.get('status') not in (200, '200') or not isinstance(result.get('data'), list):
        raise SAS4Error('SAS4 extension choices are unavailable.')
    return [{'id': int(row['id']), 'name': str(row['name'])} for row in result['data'] if isinstance(row, dict) and str(row.get('id', '')).isdigit() and row.get('name')]


def extension_quote(client, headers, profile_id, extension_id, options=None):
    options = extension_options(client, headers, profile_id) if options is None else options
    if extension_id not in [row['id'] for row in options]:
        raise HTTPException(403, 'This extension is not allowed for the user profile.')
    result = response_json(client.get(DEFAULT_SERVER + API_PATH + f'profile/{extension_id}', headers=headers))
    profile = result.get('data')
    if result.get('status') not in (200, '200') or not isinstance(profile, dict):
        raise SAS4Error('SAS4 extension price is unavailable.')
    try:
        cost = money(profile['price']) * (1 + money(profile.get('vat', 0)))
    except (ValueError, KeyError) as exc:
        raise SAS4Error('SAS4 extension price is unavailable.') from exc
    return {'id': extension_id, 'name': str(profile.get('name') or ''), 'cost': str(cost),
            'duration': profile.get('expiration_amount'), 'duration_unit': profile.get('expiration_unit')}


def fetch_recharge(connection, password, user_id, transport=None, extension_id=None):
    import uuid
    with sas4_session(connection, password, transport) as (client, headers):
        methods = recharge_permissions(user_permissions(client, headers))
        if not any(methods.values()):
            raise HTTPException(403, 'Your SAS4 account has no recharge permissions.')
        record = raw_user(client, headers, user_id)
        data = activation_info(client, headers, user_id) if methods['credit'] or methods['card'] else {}
        currency = None
        try:
            currency = response_json(client.get(DEFAULT_SERVER + API_PATH + 'resources/login', headers=headers)).get('data', {}).get('site_currency')
        except (SAS4Error, httpx.HTTPError):
            pass
        options, extension = [], None
        warning = None
        if methods['extend']:
            try:
                options = extension_options(client, headers, record['profile_id'])
                selected = extension_id or next((row['id'] for row in options if row['name'].strip().lower() == 'test'), None)
                if selected:
                    extension = extension_quote(client, headers, record['profile_id'], selected, options)
            except (SAS4Error, httpx.HTTPError, KeyError) as exc:
                warning = 'Extension choices or prices are unavailable. Reopen the recharge screen to retry.'
        def amount(key):
            try:
                return str(money(data.get(key)))
            except ValueError:
                return None
        return {'username': record.get('username'), 'profile': data.get('profile_name', record.get('profile_name')),
                'profile_id': record.get('profile_id'), 'expiration': record.get('expiration'),
                'manager_cost': amount('n_required_amount'), 'customer_price': amount('user_price'),
                'manager_balance': data.get('manager_balance') if methods['credit'] or methods['extend'] else None, 'currency': currency,
                'methods': methods, 'extensions': options, 'extension': extension, 'warning': warning,
                'transaction_id': uuid.uuid4().hex}


def redeem_card(connection, password, user_id, data, transport=None):
    with sas4_session(connection, password, transport) as (client, headers):
        require_recharge(user_permissions(client, headers), data.method)
        record = raw_user(client, headers, user_id)
        if data.method != 'card':
            if record.get('profile_id') != data.expected_profile_id or (
                data.expected_expiration is not None and record.get('expiration') != data.expected_expiration):
                raise HTTPException(409, 'The user profile or expiry changed. Reopen recharge to review it.')
        if data.method == 'extend':
            quote = extension_quote(client, headers, record['profile_id'], data.extension_id)
            cost = money(quote['cost'])
            route = 'user/extend'
            payload = {'method': 'credit', 'profile_id': data.extension_id, 'user_id': user_id, 'transaction_id': data.transaction_id}
        else:
            activation = activation_info(client, headers, user_id)
            cost = money(activation.get('n_required_amount')) if data.method == 'credit' else None
            route = 'user/activate'
            payload = {'method': data.method, 'pin': data.pin or '', 'user_id': user_id,
                'transaction_id': data.transaction_id, 'activation_units': 1, 'units': activation.get('units', 1),
                'money_collected': 0, 'user_price': activation.get('user_price'), 'issue_invoice': 0, 'comments': ''}
        if data.method != 'card' and cost != money(data.expected_cost):
            raise HTTPException(409, 'The recharge price changed. Reopen recharge to review the new amount.')
        try:
            result = response_json(client.post(DEFAULT_SERVER + API_PATH + route, headers=headers, json=wire_payload(payload)))
        except (httpx.HTTPError, SAS4Error) as exc:
            raise SAS4Error('Recharge was not confirmed. Check this user in SAS4 before trying again; the service may already have been recharged.') from exc
        if result.get('status') not in (200, '200'):
            raise HTTPException(400, 'SAS4 rejected the recharge. Check the card, balance, service eligibility, and permissions.')
        return {'recharged': True}


@router.get('/users/{user_id}/recharge')
def get_card_recharge(user_id: int, extension_id: Optional[int] = Query(None, ge=1), user=Depends(sas4_access), db=Depends(get_db)):
    if user_id < 1:
        raise HTTPException(422, 'Invalid SAS4 user ID')
    connection, password = local_user_connection(db, user)
    try:
        return fetch_recharge(connection, password, user_id, extension_id=extension_id)
    except SAS4Error as exc:
        raise HTTPException(502, str(exc)) from exc


@router.post('/users/{user_id}/recharge')
def recharge_user_card(user_id: int, data: CardRecharge, user=Depends(sas4_access), db=Depends(get_db)):
    from .api import cache
    from redis.exceptions import RedisError
    if user_id < 1:
        raise HTTPException(422, 'Invalid SAS4 user ID')
    connection, password = local_user_connection(db, user)
    key = f'sas4:recharge:{user.id}:{user_id}:{data.transaction_id}'
    try:
        if not cache.set(key, 'pending', nx=True, ex=86400):
            if cache.get(key) == 'complete':
                return {'recharged': True}
            raise HTTPException(409, 'This recharge was already submitted. Check the user before starting another recharge.')
    except RedisError as exc:
        raise HTTPException(503, 'Recharge protection is unavailable. Try again later.') from exc
    try:
        result = redeem_card(connection, password, user_id, data)
    except SAS4Error as exc:
        raise HTTPException(502, str(exc)) from exc
    try:
        cache.set(key, 'complete', ex=86400)
    except RedisError:
        pass  # Keep the original pending marker; never repeat an unconfirmed submission.
    audit(db, user, 'sas4.user.recharge', str(user_id))
    db.commit()
    return result
