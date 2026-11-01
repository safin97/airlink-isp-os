"""Enter a disposable owner only into the dedicated QEMU first-boot console."""
import json
import os
from pathlib import Path
import secrets
import sys
import time
from qemu_test import qmp, OUT


def type_text(text):
    punctuation={'/':'slash','.':'dot','-':'minus','_':'shift-minus','!':'shift-1','\n':'ret'}
    for char in text:
        key=punctuation.get(char,'shift-'+char.lower() if char.isupper() else char)
        if not (char.isalnum() or char in punctuation):raise ValueError('Unsupported test key')
        qmp('human-monitor-command',{'command-line':'sendkey '+key+' 50'})
        time.sleep(.08)

if __name__=='__main__':
    state=json.loads((OUT/'qemu-process.json').read_text())
    if state['phase']!='installed':raise SystemExit('Installed QA VM required')
    path=Path('/tmp/airlink-qemu-test-credentials.json')
    if sys.argv[1:] == ['network-default']:
        type_text('n\n')
    elif sys.argv[1:] == ['owner']:
        credentials={'username':'qa-owner','password':'Qa-'+secrets.token_hex(16)+'!'}
        fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
        with os.fdopen(fd,'w') as file:json.dump(credentials,file)
        type_text(credentials['username']+'\n')
        time.sleep(.3)
        type_text(credentials['password']+'\n')
        time.sleep(.3)
        type_text(credentials['password']+'\n')
    else:
        raise SystemExit('Choose network-default or owner after inspecting the console')
