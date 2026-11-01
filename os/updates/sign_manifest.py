"""Offline publisher utility; signing keys are never included in an ISO."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
from cryptography.hazmat.primitives.serialization import load_pem_private_key
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from update import canonical

parser=argparse.ArgumentParser()
parser.add_argument('--key',required=True,type=Path)
parser.add_argument('--package',required=True,type=Path)
parser.add_argument('--version',required=True)
parser.add_argument('--sequence',required=True,type=int)
parser.add_argument('--url',required=True)
parser.add_argument('--expires',required=True)
parser.add_argument('--notes',required=True,type=Path)
parser.add_argument('--output',required=True,type=Path)
parser.add_argument('--reboot-required',action='store_true')
args=parser.parse_args()
key=load_pem_private_key(args.key.read_bytes(),password=None)
if not isinstance(key,Ed25519PrivateKey):raise SystemExit('Ed25519 key required')
sha=hashlib.sha256()
with args.package.open('rb') as file:
    for block in iter(lambda:file.read(1024*1024),b''):sha.update(block)
meta={'version':args.version,'sequence':args.sequence,'url':args.url,'expires':args.expires,'sha256':sha.hexdigest(),
      'size':args.package.stat().st_size,'release_notes':args.notes.read_text(),'reboot_required':args.reboot_required}
args.output.write_text(json.dumps({'manifest':meta,'signature':base64.b64encode(key.sign(canonical(meta))).decode()},indent=2)+'\n')
