"""Google OAuth and resumable uploads; fixed HTTPS endpoints and bounded requests."""
import hashlib
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request

SCOPE = 'https://www.googleapis.com/auth/drive.file'
TOKEN_URL = 'https://oauth2.googleapis.com/token'
FILES_URL = 'https://www.googleapis.com/drive/v3/files'
UPLOAD_URL = 'https://www.googleapis.com/upload/drive/v3/files'
CHUNK = 8 * 1024 * 1024


class DriveError(ValueError):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def request(method, url, *, headers=None, body=None, form=None, data=None):
    parsed = urllib.parse.urlsplit(url)
    allowed = (parsed.hostname == 'oauth2.googleapis.com' and parsed.path in ('/token', '/revoke')) or (
        parsed.hostname == 'www.googleapis.com' and parsed.path.startswith(('/drive/v3/', '/upload/drive/v3/')))
    if not allowed or parsed.scheme != 'https' or parsed.port not in (None, 443) or parsed.username or parsed.password:
        raise DriveError('Google returned an unsupported endpoint')
    headers = dict(headers or {})
    if body is not None:
        data = json.dumps(body).encode(); headers['Content-Type'] = 'application/json'
    if form is not None:
        data = urllib.parse.urlencode(form).encode(); headers['Content-Type'] = 'application/x-www-form-urlencoded'
    req = urllib.request.Request(url, method=method, headers=headers, data=data)
    try:
        response = urllib.request.build_opener(NoRedirect()).open(req, timeout=60)
    except urllib.error.HTTPError as exc:
        response = exc
    except (OSError, urllib.error.URLError, ValueError):
        raise DriveError('Cannot reach Google Drive. Check the internet connection and retry.') from None
    with response:
        status, response_headers = response.code, dict(response.headers)
        raw = response.read(1024 * 1024 + 1)
    if len(raw) > 1024 * 1024:
        raise DriveError('Google returned an oversized response')
    try:
        result = json.loads(raw) if raw else {}
    except (ValueError, UnicodeDecodeError):
        result = {}
    if not isinstance(result, dict):
        raise DriveError('Google returned an invalid response')
    return status, {k.lower(): v for k, v in response_headers.items()}, result


def successful(status, result):
    if status not in (200, 201):
        if status in (400, 401) and result.get('error') in ('invalid_grant', 'invalid_client'):
            raise DriveError('Google authorization expired or was rejected. Check the OAuth client and reconnect.')
        if status == 403:
            raise DriveError('Google denied access. Check Drive API access and available storage.')
        raise DriveError('Google Drive request failed. Reconnect or retry the backup.')
    return result


def token(config, *, code=None, verifier=None):
    form = {'client_id': config['client_id'], 'client_secret': config['client_secret']}
    if code is not None:
        form.update(grant_type='authorization_code', code=code, redirect_uri=config['redirect_uri'], code_verifier=verifier)
    else:
        form.update(grant_type='refresh_token', refresh_token=config['refresh_token'])
    status, _, result = request('POST', TOKEN_URL, form=form)
    result = successful(status, result)
    for name in ('access_token', 'refresh_token'):
        value = result.get(name)
        if name == 'refresh_token' and value is None:
            continue
        if not isinstance(value, str) or not re.fullmatch(r'[\x21-\x7e]{1,8192}', value):
            raise DriveError('Google did not return a valid authorization token')
    return result


def account(access_token):
    status, _, result = request('GET', 'https://www.googleapis.com/drive/v3/about?fields=user(emailAddress)',
                                 headers={'Authorization': 'Bearer ' + access_token})
    return successful(status, result).get('user', {}).get('emailAddress', '')


def file_id(value):
    if not isinstance(value, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,200}', value):
        raise DriveError('Google returned an invalid file identifier')
    return value


def folder(access_token, name, existing=None):
    headers = {'Authorization': 'Bearer ' + access_token}
    if existing:
        status, _, result = request('GET', FILES_URL+'/'+file_id(existing)+'?fields=id,mimeType,trashed', headers=headers)
        if status == 200 and result.get('mimeType') == 'application/vnd.google-apps.folder' and not result.get('trashed'):
            return file_id(result['id'])
        if status != 404:
            raise DriveError('The backup folder is unavailable. Reconnect Google Drive to create a new folder.')
    status, _, result = request('POST', FILES_URL+'?fields=id', headers=headers,
        body={'name': name, 'mimeType': 'application/vnd.google-apps.folder', 'appProperties': {'airlink_backups': '1'}})
    return file_id(successful(status, result)['id'])


def upload(access_token, folder_id, path, progress):
    size = path.stat().st_size
    sha, md5 = hashlib.sha256(), hashlib.md5()
    with path.open('rb') as source:
        for block in iter(lambda: source.read(CHUNK), b''):
            sha.update(block); md5.update(block)
    headers = {'Authorization': 'Bearer ' + access_token}
    status, response_headers, result = request('POST', UPLOAD_URL+'?uploadType=resumable&fields=id,name,size,md5Checksum',
        headers={**headers, 'X-Upload-Content-Type': 'application/octet-stream', 'X-Upload-Content-Length': str(size)},
        body={'name': path.name, 'parents': [file_id(folder_id)], 'appProperties': {'airlink_backup': '1', 'sha256': sha.hexdigest()}})
    successful(status, result)
    location = response_headers.get('location', '')
    parsed = urllib.parse.urlsplit(location)
    if parsed.scheme != 'https' or parsed.netloc != 'www.googleapis.com' or parsed.path != '/upload/drive/v3/files':
        raise DriveError('Google returned an unsupported upload destination')
    offset, attempts, deadline = 0, 0, time.monotonic() + 3600
    with path.open('rb') as source:
        while time.monotonic() < deadline:
            source.seek(offset)
            block = source.read(CHUNK)
            if not block:
                status, reply_headers, result = request('PUT', location, headers={**headers, 'Content-Range': f'bytes */{size}'}, data=b'')
            else:
                try:
                    status, reply_headers, result = request('PUT', location, headers={**headers,
                        'Content-Range': f'bytes {offset}-{offset+len(block)-1}/{size}', 'Content-Type': 'application/octet-stream'}, data=block)
                except DriveError:
                    status = 503
                if status >= 500 or status == 429:
                    attempts += 1
                    if attempts > 3:
                        raise DriveError('Google upload was interrupted. Retry the backup.')
                    status, reply_headers, result = request('PUT', location, headers={**headers, 'Content-Range': f'bytes */{size}'}, data=b'')
            if status in (200, 201):
                if str(result.get('size')) != str(size) or result.get('md5Checksum') != md5.hexdigest():
                    raise DriveError('Google upload could not be verified; it is not marked as a completed backup.')
                ident = file_id(result.get('id'))
                progress(size, size)
                return {'file_id': ident, 'file_url': 'https://drive.google.com/file/d/'+ident+'/view',
                        'size': size, 'sha256': sha.hexdigest(), 'filename': path.name}
            if status != 308:
                successful(status, result)
            match = re.fullmatch(r'bytes=0-(\d+)', reply_headers.get('range', ''))
            next_offset = int(match.group(1)) + 1 if match else 0
            if not offset <= next_offset <= min(size, offset + len(block)):
                raise DriveError('Google returned an invalid upload position')
            if next_offset == offset:
                attempts += 1
                if attempts > 3:
                    raise DriveError('Google upload stopped making progress. Retry the backup.')
            else:
                attempts = 0
            offset = next_offset
            progress(offset, size)
    raise DriveError('Google Drive backup exceeded the upload time limit')
