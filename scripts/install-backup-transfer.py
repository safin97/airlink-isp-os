"""Install the official, pinned rclone distribution with verified MEGA support."""
import argparse
import hashlib
from pathlib import Path
import platform
import shutil
import subprocess
import tempfile
import zipfile

VERSION = 'v1.76.0'
CHECKSUMS = {
    ('linux', 'amd64'): 'b00f00b3266c3764413afe599d3ec316f6f43b3e0ea8a0bc1d186d2133e46df7',
    ('linux', 'arm64'): 'ee169016675e23a69d77240565133ff7dbc9b33d16fa8f7053d4af39f1eaeb78',
    ('osx', 'amd64'): '4f5835733d52b818340f97b1fc0348a70461534d123363a183ca2b660219595a',
    ('osx', 'arm64'): 'e72dc90b70f4947a7b72b61bde4a4fbba5777b2874fb448951ffdde67ebd0ab7',
}
ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT/'.tools')
    args = parser.parse_args()
    system = {'Darwin': 'osx', 'Linux': 'linux'}.get(platform.system())
    arch = {'arm64': 'arm64', 'aarch64': 'arm64', 'x86_64': 'amd64', 'AMD64': 'amd64'}.get(platform.machine())
    if not system or not arch:
        raise SystemExit('Install rclone from https://rclone.org/install/ for this platform.')
    name = f'rclone-{VERSION}-{system}-{arch}'
    filename = name + '.zip'
    base = f'https://downloads.rclone.org/{VERSION}/'
    expected = CHECKSUMS[(system, arch)]
    with tempfile.TemporaryDirectory(prefix='airlink-rclone-') as temporary:
        archive = Path(temporary)/filename
        subprocess.run(['curl', '--fail', '--silent', '--show-error', '--location', '--proto', '=https', '--proto-redir', '=https',
                        '--max-time', '120', '--output', str(archive), base+filename], check=True)
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        if digest != expected:
            raise SystemExit('Checksum mismatch; nothing installed.')
        tools = args.output; tools.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(archive) as bundle:
            target = tools/'rclone.new'
            with bundle.open(name+'/rclone') as source, target.open('wb') as output:
                shutil.copyfileobj(source, output)
            target.chmod(0o755)
            # Some distribution builds omit MEGA. Never publish one of those as a backup helper.
            try:
                subprocess.run([str(target), 'help', 'backend', 'mega'], check=True,
                               capture_output=True, timeout=30)
            except (OSError, subprocess.SubprocessError):
                target.unlink(missing_ok=True)
                raise SystemExit('Transfer binary lacks working MEGA support; existing installation kept.') from None
            target.replace(tools/'rclone')
            for member in bundle.namelist():
                if Path(member).name in ('COPYING', 'README.txt'):
                    (tools/('rclone-'+Path(member).name)).write_bytes(bundle.read(member))
    print(f'Installed rclone {VERSION} to {tools / "rclone"}; official SHA-256 verified.')


if __name__ == '__main__':
    main()
