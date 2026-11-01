"""Prepare public GitHub Releases for AirLink's existing signed updater.

Runs on the publisher workstation. It never uploads, installs, or executes a package.
"""
import argparse
import base64
import hashlib
import json
import os
import re
import shutil
from pathlib import Path
from urllib.parse import quote, urlsplit

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

try:
    from .update import canonical, verify_manifest
except ImportError:
    from update import canonical, verify_manifest


def repository(value):
    value = value.strip()
    if value.startswith('https://'):
        url = urlsplit(value)
        if url.netloc != 'github.com' or url.query or url.fragment:
            raise ValueError('Use https://github.com/OWNER/REPOSITORY')
        value = url.path.strip('/')
    if value.endswith('.git'):
        value = value[:-4]
    parts = value.split('/')
    if (len(parts) != 2 or not re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?', parts[0])
            or not re.fullmatch(r'[A-Za-z0-9_.-]{1,100}', parts[1]) or parts[1] in {'.', '..'}):
        raise ValueError('Expected a GitHub OWNER/REPOSITORY or HTTPS repository URL')
    return '/'.join(parts)


def digest(path):
    sha = hashlib.sha256()
    with Path(path).open('rb') as source:
        for block in iter(lambda: source.read(1024 * 1024), b''):
            sha.update(block)
    return sha.hexdigest()


def public_bytes(key):
    return key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def init_key(directory):
    directory = Path(directory)
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    private = directory / 'publisher-private.pem'
    public = directory / 'update-public-key.bin'
    if private.exists() or public.exists():
        raise ValueError('A publisher key already exists; refusing to replace it')
    key = Ed25519PrivateKey.generate()
    # O_EXCL and 0600 prevent accidental replacement or broadly readable key material.
    fd = os.open(private, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as output:
        output.write(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                       serialization.NoEncryption()))
    with public.open('xb') as output:
        output.write(public_bytes(key))
    return public


def configuration(repo, public_key, output):
    repo = repository(repo)
    raw = Path(public_key).read_bytes()
    Ed25519PublicKey.from_public_bytes(raw)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    config = {'manifest_url': f'https://github.com/{repo}/releases/latest/download/stable.json'}
    destinations = (output / 'update-source.json', output / 'update-public-key.bin')
    # Explicitly refuse to replace a different trust anchor in an existing bundle.
    if destinations[1].exists() and destinations[1].read_bytes() != raw:
        raise ValueError('Output already contains another publisher key; use a new directory')
    destinations[1].write_bytes(raw)
    destinations[0].write_text(json.dumps(config, indent=2) + '\n')
    return {'repository': repo, 'manifest_url': config['manifest_url'],
            'public_key_sha256': hashlib.sha256(raw).hexdigest()}


def prepare(repo, key_file, package, version, sequence, expires, notes, output, reboot_required=False):
    repo = repository(repo)
    if not re.fullmatch(r'[0-9][A-Za-z0-9.+~-]{0,39}', version):
        raise ValueError('Invalid Debian version')
    key = serialization.load_pem_private_key(Path(key_file).read_bytes(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError('Ed25519 publisher key required')
    package = Path(package)
    asset = f'airlink-isp-os_{version}_amd64.deb'
    tag = 'v' + version
    meta = {'version': version, 'sequence': sequence, 'sha256': digest(package),
            'size': package.stat().st_size,
            'url': f'https://github.com/{repo}/releases/download/{quote(tag, safe="")}/{quote(asset, safe="")}',
            'expires': expires, 'release_notes': Path(notes).read_text(),
            'reboot_required': reboot_required}
    envelope = {'manifest': meta, 'signature': base64.b64encode(key.sign(canonical(meta))).decode()}
    verify_manifest(envelope, public_bytes(key))
    # A fresh directory avoids mixing an old manifest with a different package.
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(package, output / asset)
    (output / 'stable.json').write_text(json.dumps(envelope, indent=2) + '\n')
    (output / 'release-notes.md').write_text(meta['release_notes'])
    (output / 'SHA256SUMS').write_text(''.join(
        f'{digest(output / name)}  {name}\n' for name in (asset, 'stable.json')))
    return {'repository': repo, 'tag': tag, 'directory': str(output), 'assets': [asset, 'stable.json']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    key = commands.add_parser('init-key', help='Generate an offline publisher key; never replaces one')
    key.add_argument('--directory', required=True, type=Path)
    config = commands.add_parser('configure', help='Create configuration files for an installed appliance')
    config.add_argument('--repo', required=True)
    config.add_argument('--public-key', required=True, type=Path)
    config.add_argument('--output', required=True, type=Path)
    release = commands.add_parser('prepare', help='Sign a manifest and stage release assets; does not publish')
    for name in ('repo', 'version', 'expires'):
        release.add_argument('--' + name, required=True)
    for name in ('key', 'package', 'notes', 'output'):
        release.add_argument('--' + name, required=True, type=Path)
    release.add_argument('--sequence', required=True, type=int)
    release.add_argument('--reboot-required', action='store_true')
    args = parser.parse_args()
    try:
        if args.command == 'init-key':
            public = init_key(args.directory)
            result = {'public_key': str(public), 'public_key_sha256': digest(public)}
        elif args.command == 'configure':
            result = configuration(args.repo, args.public_key, args.output)
        else:
            result = prepare(args.repo, args.key, args.package, args.version, args.sequence,
                             args.expires, args.notes, args.output, args.reboot_required)
        print(json.dumps(result, indent=2))
    except (ValueError, OSError) as exc:
        parser.exit(1, f'{exc}\n')


if __name__ == '__main__':
    main()
