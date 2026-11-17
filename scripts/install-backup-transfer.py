"""Install a checksum-verified rclone binary inside this checkout for local MEGA backups."""
import hashlib
from pathlib import Path
import platform
import shutil
import subprocess
import tempfile
import zipfile

VERSION = 'v1.76.0'
ROOT = Path(__file__).resolve().parents[1]


def main():
    system = {'Darwin': 'osx', 'Linux': 'linux'}.get(platform.system())
    arch = {'arm64': 'arm64', 'aarch64': 'arm64', 'x86_64': 'amd64', 'AMD64': 'amd64'}.get(platform.machine())
    if not system or not arch:
        raise SystemExit('Install rclone from https://rclone.org/install/ for this platform.')
    name = f'rclone-{VERSION}-{system}-{arch}'
    filename = name + '.zip'
    base = f'https://downloads.rclone.org/{VERSION}/'
    checksums = subprocess.check_output(['curl', '--fail', '--silent', '--show-error', '--location',
        '--proto', '=https', '--max-time', '30', base+'SHA256SUMS'], text=True)
    expected = next((parts[0] for line in checksums.splitlines()
                     if len(parts := line.split()) == 2 and parts[1].lstrip('*') == filename), None)
    if not expected:
        raise SystemExit('Official checksum not found; nothing installed.')
    with tempfile.TemporaryDirectory(prefix='airlink-rclone-') as temporary:
        archive = Path(temporary)/filename
        subprocess.run(['curl', '--fail', '--silent', '--show-error', '--location', '--proto', '=https',
                        '--max-time', '120', '--output', str(archive), base+filename], check=True)
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        if digest != expected:
            raise SystemExit('Checksum mismatch; nothing installed.')
        tools = ROOT/'.tools'; tools.mkdir(exist_ok=True)
        with zipfile.ZipFile(archive) as bundle:
            target = tools/'rclone.new'
            with bundle.open(name+'/rclone') as source, target.open('wb') as output:
                shutil.copyfileobj(source, output)
            target.chmod(0o755)
            target.replace(tools/'rclone')
            for member in bundle.namelist():
                if Path(member).name in ('COPYING', 'README.txt'):
                    (tools/('rclone-'+Path(member).name)).write_bytes(bundle.read(member))
    print(f'Installed rclone {VERSION} to {tools / "rclone"}; official SHA-256 verified.')


if __name__ == '__main__':
    main()
