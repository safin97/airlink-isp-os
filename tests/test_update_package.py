import hashlib
import shutil
import subprocess
import pytest
from updates import update


@pytest.mark.skipif(not shutil.which('dpkg-deb'),reason='Debian package validation requires Linux dpkg-deb')
def test_real_debian_package_identity_and_tampering(tmp_path,monkeypatch):
    stage=tmp_path/'stage'
    (stage/'DEBIAN').mkdir(parents=True)
    (stage/'DEBIAN/control').write_text('Package: airlink-isp-os\nVersion: 0.2.0\nArchitecture: amd64\nMaintainer: QA <qa@example.invalid>\nDescription: Disposable verification fixture\n')
    package=tmp_path/'package.deb'
    subprocess.run(['dpkg-deb','--root-owner-group','--build',str(stage),str(package)],check=True,capture_output=True)
    monkeypatch.setattr(update,'ROOT',tmp_path)
    meta={'version':'0.2.0','size':package.stat().st_size,'sha256':hashlib.sha256(package.read_bytes()).hexdigest()}
    update.verify_package(meta)
    with pytest.raises(ValueError,match='identity'):
        update.verify_package({**meta,'version':'9.9.9'})
    package.write_bytes(package.read_bytes()+b'tampered')
    with pytest.raises(ValueError,match='size'):
        update.verify_package(meta)
