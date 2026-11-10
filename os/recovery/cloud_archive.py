"""Authenticated streaming backup encryption and offline recovery.

Decrypt: python3 cloud_archive.py INPUT.tar.airlink OUTPUT.tar
The password is read privately from the terminal, never from command arguments.
"""
import argparse
import getpass
import os
from pathlib import Path
import tempfile
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

MAGIC = b'AIRLINK-BACKUP\x01'
CHUNK = 1024 * 1024


def key(password, salt):
    return Scrypt(salt=salt, length=32, n=32768, r=8, p=1).derive(password.encode('utf-8'))


def transform(source, destination, password, *, decrypt=False):
    source, destination = Path(source), Path(destination)
    if destination.exists():
        raise ValueError('Output already exists; choose a new filename')
    if not password:
        raise ValueError('Enter the backup encryption password')
    temporary = None
    try:
        with source.open('rb') as original:
            if decrypt:
                header = original.read(len(MAGIC) + 28)
                if len(header) != len(MAGIC) + 28 or not header.startswith(MAGIC):
                    raise ValueError('Not a supported AirLink encrypted backup')
                remaining = source.stat().st_size - len(header) - 16
                if remaining < 0:
                    raise ValueError('Incomplete backup')
                salt, nonce = header[len(MAGIC):len(MAGIC)+16], header[-12:]
                original.seek(-16, os.SEEK_END)
                tag = original.read(16)
                original.seek(len(header))
                operation = Cipher(algorithms.AES(key(password, salt)), modes.GCM(nonce, tag)).decryptor()
            else:
                salt, nonce = os.urandom(16), os.urandom(12)
                header = MAGIC + salt + nonce
                remaining = source.stat().st_size
                operation = Cipher(algorithms.AES(key(password, salt)), modes.GCM(nonce)).encryptor()
            operation.authenticate_additional_data(header)
            fd, temporary = tempfile.mkstemp(prefix='.airlink-backup-', dir=destination.parent)
            with os.fdopen(fd, 'wb') as output:
                if not decrypt:
                    output.write(header)
                while remaining:
                    block = original.read(min(CHUNK, remaining))
                    if not block:
                        raise ValueError('Incomplete backup')
                    remaining -= len(block)
                    output.write(operation.update(block))
                output.write(operation.finalize())
                if not decrypt:
                    output.write(operation.tag)
                output.flush()
                os.fsync(output.fileno())
            # Never replace an existing recovery file, even if it appeared during decryption.
            os.link(temporary, destination)
    finally:
        if temporary:
            Path(temporary).unlink(missing_ok=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    try:
        transform(args.input, args.output, getpass.getpass('Backup encryption password: '), decrypt=True)
        print('Backup decrypted. Review the archive before using the local restore procedure.')
    except Exception:
        parser.exit(1, 'Decryption failed. Check the password and backup integrity; no output was published.\n')
