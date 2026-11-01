"""Explicit, disposable x86_64 UEFI integration harness. Never attaches host disks."""
import argparse
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import time

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'test-results'


def qmp(command, arguments=None):
    with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as connection:
        connection.settimeout(15)
        connection.connect('/tmp/airlink-qa-qmp.sock')
        stream=connection.makefile('rwb',buffering=0)
        stream.readline()
        stream.write(b'{"execute":"qmp_capabilities"}\n')
        while 'return' not in json.loads(stream.readline()):pass
        stream.write(json.dumps({'execute':command,**({'arguments':arguments} if arguments else {})}).encode()+b'\n')
        while True:
            result=json.loads(stream.readline())
            if 'return' in result:return result['return']
            if 'error' in result:raise RuntimeError(result['error'])


def launch(phase):
    OUT.mkdir(exist_ok=True)
    sock=Path('/tmp/airlink-qa-qmp.sock')
    if sock.exists():
        raise RuntimeError('A QA QMP socket already exists; stop that VM before launching another')
    firmware=Path(os.getenv('OVMF_CODE','/opt/homebrew/share/qemu/edk2-x86_64-code.fd'))
    variables=Path(os.getenv('OVMF_VARS','/opt/homebrew/share/qemu/edk2-i386-vars.fd'))
    if not firmware.is_file() or not variables.is_file():
        raise RuntimeError('Set OVMF_CODE and OVMF_VARS to installed UEFI firmware files')
    args=['qemu-system-x86_64','-machine','q35,accel=tcg','-cpu','max','-smp','2','-m','4096',
          '-display','none','-vga','std','-no-reboot','-smbios','type=1,manufacturer=AirLinkQA,product=AirLinkQA',
          '-nic','user,model=virtio-net-pci,hostfwd=tcp:127.0.0.1:18443-:443',
          '-qmp','unix:/tmp/airlink-qa-qmp.sock,server=on,wait=off',
          '-serial','file:'+str(OUT/(phase+'-serial.log')),
          '-drive','if=pflash,format=raw,readonly=on,file='+str(firmware)]
    varfile=OUT/(phase+'-vars.fd')
    shutil.copyfile(variables,varfile)
    args+=['-drive','if=pflash,format=raw,file='+str(varfile)]
    target=OUT/'target.qcow2'
    protected=OUT/'protected.raw'
    if phase in ('install','installed'):
        if phase=='install':
            if target.exists():raise RuntimeError('Target already exists; archive the previous QA disk before a new test')
            subprocess.run(['qemu-img','create','-f','qcow2',str(target),'40G'],check=True)
            with open(protected,'wb') as disk:
                disk.write(b'AIRLINK_PROTECTED_DISK_SENTINEL\n')
                disk.truncate(64*1024**2)
        args+=['-drive','if=none,id=target,format=qcow2,file='+str(target),'-device','virtio-blk-pci,drive=target,serial=AIRLINK-QA-TARGET',
               '-drive','if=none,id=protected,format=raw,file='+str(protected),'-device','virtio-blk-pci,drive=protected,serial=AIRLINK-QA-PROTECTED']
    if phase in ('live','install'):
        args+=['-cdrom',str(ROOT/'dist/AirLink-ISP-OS-amd64.iso'),'-boot','d']
    if phase=='install':
        args+=['-kernel',str(ROOT/'dist/image/live/vmlinuz'),'-initrd',str(ROOT/'dist/image/live/initrd.img'),
               '-append','boot=live components console=tty0 console=ttyS0,115200n8 airlink.mode=install airlink.qa=install']
    with open(OUT/(phase+'-qemu.log'),'w') as log:
        process=subprocess.Popen(args,stdout=log,stderr=log,start_new_session=True)
    (OUT/'qemu-process.json').write_text(json.dumps({'pid':process.pid,'phase':phase,'args':args},indent=2))
    print(json.dumps({'pid':process.pid,'phase':phase,'https':'https://127.0.0.1:18443/'}))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=['live','install','installed','screenshot','stop','poweroff','keys'])
    parser.add_argument('value',nargs='?')
    args=parser.parse_args()
    if args.action=='screenshot':
        output=OUT/(args.value or 'qemu-screen.ppm')
        qmp('screendump',{'filename':str(output)})
        print(output)
    elif args.action=='poweroff':
        qmp('system_powerdown')
    elif args.action=='stop':
        qmp('quit')
    elif args.action=='keys':
        print(qmp('human-monitor-command',{'command-line':'sendkey '+args.value}))
    else:launch(args.action)
