"""Install the initial publisher configuration without replacing existing trust."""
import argparse
import json
import os
import tempfile
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

try:
    from .github_release import repository
except ImportError:
    from github_release import repository


def install_source(source, destination):
    source, destination = Path(source), Path(destination)
    key = (source / 'update-public-key.bin').read_bytes()
    Ed25519PublicKey.from_public_bytes(key)
    config = json.loads((source / 'update-source.json').read_text())
    url = config.get('manifest_url', '')
    prefix, suffix = 'https://github.com/', '/releases/latest/download/stable.json'
    if set(config) != {'manifest_url'} or not url.startswith(prefix) or not url.endswith(suffix):
        raise ValueError('Expected a GitHub latest-release manifest URL')
    repo = repository(url[len(prefix):-len(suffix)])
    if url != prefix + repo + suffix:
        raise ValueError('Noncanonical GitHub update URL')
    destination.mkdir(parents=True, exist_ok=True)
    files = {'update-public-key.bin': key,
             'update-source.json': (json.dumps(config, indent=2) + '\n').encode()}
    # Preflight both paths before changing either. Existing site-specific trust wins.
    for name, data in files.items():
        target = destination / name
        if target.is_symlink():
            raise ValueError('Refusing a symbolic-link configuration target')
        if target.exists():
            existing = target.read_bytes()
            matches = (json.loads(existing) == config if name.endswith('.json') else existing == data)
            if not matches:
                raise ValueError('Existing publisher configuration differs; refusing to replace trust')
    for name, data in files.items():
        target = destination / name
        if target.exists():
            continue
        fd, temporary = tempfile.mkstemp(prefix='.airlink-source-', dir=destination)
        try:
            with os.fdopen(fd, 'wb') as output:
                output.write(data)
                output.flush()
                os.fsync(output.fileno())
            os.chmod(temporary, 0o644)
            os.replace(temporary, target)
        finally:
            Path(temporary).unlink(missing_ok=True)
    return repo


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=Path('/opt/airlink/deployment/update-source'))
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.exit(1, 'Run on the AirLink appliance as root.\n')
    if not Path('/opt/airlink/backend/airlink').is_dir():
        parser.exit(1, 'Run on the AirLink appliance, not the publisher workstation.\n')
    try:
        repo = install_source(args.source, Path('/etc/airlink'))
    except (ValueError, OSError) as exc:
        parser.exit(1, str(exc) + '\n')
    print('Configured signed GitHub updates from ' + repo)


if __name__ == '__main__':
    main()
