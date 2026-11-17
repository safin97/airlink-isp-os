"""Bounded local uploads. Uses the appliance's existing publisher key, never a key in a file.

All operations run under the updater lock. Uploaded content is never executed or
extracted to caller-controlled paths. Installation uses the normal backup/health job.
"""
import base64
import binascii
import json
import secrets
import shutil
import stat
import struct
import time
import zipfile
import uuid

from . import update

CHUNK = 32768
MAX_BUNDLE = update.MAX_PACKAGE + 256 * 1024
TTL = 3600


def cleanup(directory):
    shutil.rmtree(directory, ignore_errors=True)


def validate(directory):
    envelope = update.read(directory / 'manifest.json', {})
    sequence = update.read(update.ROOT / 'installed.json', {'sequence': 0})['sequence']
    try:
        meta = update.verify_manifest(envelope, update.KEY.read_bytes(), sequence)
    except Exception as exc:
        raise ValueError('Update signature is invalid, expired, or older than the installed release.') from exc
    update.verify_package(meta, directory / 'package.deb')
    return envelope, meta


def unpack(directory):
    try:
        # Bound central-directory parsing before ZipFile allocates entries. Our
        # publisher emits two ordinary, uncompressed entries and no ZIP comment.
        archive_path = directory / 'upload'
        with archive_path.open('rb') as source:
            if archive_path.stat().st_size < 22:
                raise ValueError('Invalid update archive')
            source.seek(-22, 2)
            end = struct.unpack('<4s4H2LH', source.read(22))
            if (end[:5] != (b'PK\x05\x06', 0, 0, 2, 2) or end[5] > 65536
                    or end[6] + end[5] != archive_path.stat().st_size - 22 or end[7] != 0):
                raise ValueError('Choose an official .airlink-update file.')
        with zipfile.ZipFile(directory / 'upload') as bundle:
            members = bundle.infolist()
            if len(members) != 2 or {m.filename for m in members} != {'manifest.json', 'package.deb'}:
                raise ValueError('Choose an official .airlink-update file containing its signed manifest and package.')
            for member in members:
                kind = stat.S_IFMT(member.external_attr >> 16)
                if kind not in (0, stat.S_IFREG) or member.flag_bits & 1 or member.compress_type != zipfile.ZIP_STORED:
                    raise ValueError('Unsupported update archive entry')
                limit = 128 * 1024 if member.filename == 'manifest.json' else update.MAX_PACKAGE
                if not 0 < member.file_size <= limit:
                    raise ValueError('Invalid update archive size')
            # Authenticate the small manifest before reading the package.
            raw = bundle.read('manifest.json')
            try:
                envelope = json.loads(raw)
                sequence = update.read(update.ROOT / 'installed.json', {'sequence': 0})['sequence']
                meta = update.verify_manifest(envelope, update.KEY.read_bytes(), sequence)
            except Exception as exc:
                raise ValueError('Update signature is invalid, expired, or older than the installed release.') from exc
            if bundle.getinfo('package.deb').file_size != meta['size']:
                raise ValueError('Package size mismatch')
            with bundle.open('package.deb') as source, (directory / 'package.deb').open('wb') as target:
                shutil.copyfileobj(source, target, 1024 * 1024)
            update.atomic(directory / 'manifest.json', envelope)
        return validate(directory)[1]
    except (zipfile.BadZipFile, EOFError) as exc:
        raise ValueError('Invalid or damaged update file. Download the .airlink-update file again.') from exc


def action(name, payload):
    directory = update.ROOT / 'local-upload'
    state_path = directory / 'upload.json'
    state = update.read(state_path, {})
    if state and time.time() > state['expires']:
        cleanup(directory)
        state = {}
    if name == 'cancel':
        if not state:
            return {'status': 'cancelled'}
    else:
        update.guard_pc_updates()
        if update.restart_status()['pending']:
            raise ValueError('A system restart is pending. Wait for the server to return.')
        if update.read(update.ROOT / 'state.json', {}).get('status') in {'queued', 'installing', 'failed'}:
            raise ValueError('An active or failed installation requires local review')
    user_id = payload.get('user_id')
    try:
        uuid.UUID(user_id)
    except (ValueError, TypeError, AttributeError):
        raise ValueError('Authenticated update user required') from None
    if name == 'start':
        if state:
            # A retry by this user can replace an abandoned upload; other users cannot.
            if state['user_id'] != user_id:
                raise ValueError('Another user is uploading an update. Retry after it finishes or expires.')
        size = payload.get('size')
        if type(size) is not int or not 0 < size <= MAX_BUNDLE:
            raise ValueError('Choose an update file up to 2 GiB.')
        if shutil.disk_usage(update.ROOT).free < size * 3 + 1024**3:
            raise ValueError('Insufficient space for the local update and backup')
        cleanup(directory)
        directory.mkdir(mode=0o700)
        state = {'token': secrets.token_urlsafe(32), 'user_id': user_id, 'size': size,
                 'received': 0, 'status': 'uploading', 'expires': time.time() + TTL}
        (directory / 'upload').touch(mode=0o600)
        update.atomic(state_path, state)
        return {k: state[k] for k in ('token', 'received', 'status')}
    if not state or state['user_id'] != user_id or not secrets.compare_digest(str(payload.get('token', '')), state['token']):
        raise ValueError('Local update upload expired or belongs to another user. Browse and try again.')
    if name == 'cancel':
        cleanup(directory)
        return {'status': 'cancelled'}
    if name == 'chunk':
        if state['status'] != 'uploading':
            raise ValueError('This update has already been verified')
        offset, encoded = payload.get('offset'), payload.get('data')
        if type(offset) is not int or offset != state['received']:
            raise ValueError('Upload offset mismatch. Browse and try again.')
        if not isinstance(encoded, str) or len(encoded) > 4 * ((CHUNK + 2) // 3):
            raise ValueError('Invalid update chunk')
        try:
            block = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error) as exc:
            raise ValueError('Invalid update chunk') from exc
        if not 0 < len(block) <= CHUNK or offset + len(block) > state['size']:
            raise ValueError('Update chunk exceeds expected size')
        with (directory / 'upload').open('r+b') as target:
            target.seek(offset)
            target.write(block)
            target.truncate()
        state.update(received=offset + len(block), expires=time.time() + TTL)
        update.atomic(state_path, state)
        return {'received': state['received']}
    if name == 'finish':
        if state['received'] != state['size']:
            raise ValueError('Upload incomplete. Browse and try again.')
        meta = unpack(directory)
        state.update(status='ready', expires=time.time() + TTL)
        update.atomic(state_path, state)
        return {'status': 'ready', 'release': meta}
    if name == 'install':
        if state['status'] != 'ready' or payload.get('confirm') is not True:
            raise ValueError('Verify and confirm the local update before installing')
        envelope, meta = validate(directory)
        if any(payload.get(field) != meta[field] for field in ('version', 'sequence')):
            raise ValueError('Local update changed. Browse and verify again.')
        # Copy to a fixed temporary path first. No incomplete package becomes installable.
        staged = update.ROOT / 'local-package.partial'
        shutil.copyfile(directory / 'package.deb', staged)
        staged.replace(update.ROOT / 'package.deb')
        update.atomic(update.ROOT / 'manifest.json', envelope)
        update.atomic(update.ROOT / 'verified.json', meta)
        update.queue_install(meta)
        cleanup(directory)
        return {'status': 'install', 'version': meta['version']}
    raise ValueError('Unsupported local update action')
