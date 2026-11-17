"""Strict extraction of authenticated AirLink recovery archives."""
import hashlib
import re
import shutil
import tarfile

LOCAL = {'database.sqlite', 'recovery.json', 'README.txt', 'SHA256SUMS'}
APPLIANCE = {'database.dump', 'configuration.tar.gz', 'SHA256SUMS'}
MAX_ARCHIVE_BYTES = 20 * 1024 ** 3


def extract(source, destination, local):
    expected = LOCAL if local else APPLIANCE
    destination.mkdir(mode=0o700)
    with tarfile.open(source, 'r:') as bundle:
        seen, total = set(), 0
        for member in bundle:
            total += member.size
            if (member.name not in expected or member.name in seen or not member.isfile()
                    or member.size < 0 or total > MAX_ARCHIVE_BYTES
                    or (member.name in {'SHA256SUMS', 'recovery.json', 'README.txt'} and member.size > 65536)):
                raise ValueError('Unsupported or unsafe backup archive')
            seen.add(member.name)
            with bundle.extractfile(member) as source_file, (destination/member.name).open('xb') as target:
                (destination/member.name).chmod(0o600)
                shutil.copyfileobj(source_file, target)
    if seen != expected:
        raise ValueError('This backup is incomplete or was created for a different AirLink platform')
    checksums = {}
    for line in (destination/'SHA256SUMS').read_text().splitlines():
        match = re.fullmatch(r'([0-9a-f]{64})  ([A-Za-z0-9_.-]+)', line)
        if not match or match[2] in checksums or match[2] not in expected - {'SHA256SUMS'}:
            raise ValueError('Invalid backup checksums')
        checksums[match[2]] = match[1]
    if set(checksums) != expected - {'SHA256SUMS'}:
        raise ValueError('Missing backup checksums')
    for name, checksum in checksums.items():
        digest = hashlib.sha256()
        with (destination/name).open('rb') as file:
            for block in iter(lambda: file.read(1024 * 1024), b''):
                digest.update(block)
        if digest.hexdigest() != checksum:
            raise ValueError('Backup integrity check failed')
