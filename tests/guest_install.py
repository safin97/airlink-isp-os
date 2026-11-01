"""Only executes with an explicit boot argument and a uniquely identified QEMU disk."""
import hashlib
import json
import subprocess
import sys
from pathlib import Path
sys.path.insert(0, '/opt/airlink/os')
from installer.disks import discover
from installer.install import install


def serial(message):
    print(message, flush=True)
    with open('/dev/ttyS0','w') as stream:
        stream.write(message+'\n')


def main():
    if 'airlink.qa=install' not in Path('/proc/cmdline').read_text().split():
        raise RuntimeError('Explicit QA boot flag required')
    if Path('/sys/class/dmi/id/sys_vendor').read_text().strip() != 'AirLinkQA':
        raise RuntimeError('Dedicated AirLinkQA virtual machine required')
    disks=discover()
    targets=[d for d in disks if d.serial=='AIRLINK-QA-TARGET' and d.size==40*1024**3]
    protected=[d for d in disks if d.serial=='AIRLINK-QA-PROTECTED']
    if len(targets)!=1 or len(protected)!=1:
        raise RuntimeError('Expected QA disks are missing')
    def checksum():
        with open(protected[0].path,'rb') as source:
            digest=hashlib.sha256()
            for block in iter(lambda:source.read(1024*1024),b''):digest.update(block)
            return digest.hexdigest()
    before=checksum()
    d=targets[0]
    install(d.path,d.identity,'ERASE',True,serial)
    if checksum()!=before:
        raise RuntimeError('Protected disk changed')
    serial('AIRLINK_QA_PROTECTED_DISK_UNCHANGED')
    serial('AIRLINK_QA_INSTALL_OK')
    subprocess.run(['systemctl','poweroff'],check=True)

if __name__=='__main__':
    try:
        main()
    except Exception as exc:
        serial('AIRLINK_QA_INSTALL_FAILED: '+str(exc))
        raise
