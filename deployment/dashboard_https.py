"""Maintain AirLink's local-IP HTTPS certificate without replacing custom certificates."""
import ipaddress
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
from datetime import datetime, timedelta, timezone
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.x509.oid import NameOID, ExtendedKeyUsageOID

SUBJECT = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, 'airlink.local'),
                     x509.NameAttribute(NameOID.ORGANIZATION_NAME, 'AirLink ISP OS')])


def local_addresses():
    addresses = {'127.0.0.1', '::1'}
    result = subprocess.run(['ip', '-j', 'address', 'show'], capture_output=True, text=True, check=True, timeout=10)
    for interface in json.loads(result.stdout):
        for item in interface.get('addr_info', []):
            value = ipaddress.ip_address(item['local'])
            if not value.is_link_local and not value.is_multicast and not value.is_unspecified:
                addresses.add(str(value))
    return addresses


def atomic(path, content, mode):
    fd, name = tempfile.mkstemp(prefix='.https-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            os.fchmod(stream.fileno(), mode)
            stream.write(content); stream.flush(); os.fsync(stream.fileno())
        Path(name).replace(path)
    finally:
        Path(name).unlink(missing_ok=True)


def ensure_certificate(directory, addresses):
    directory = Path(directory); directory.mkdir(parents=True, exist_ok=True)
    key_path, cert_path = directory / 'tls.key', directory / 'tls.crt'
    names = [x509.DNSName('airlink.local'), x509.DNSName('airlink')]
    names += [x509.IPAddress(ipaddress.ip_address(value)) for value in sorted(addresses)]
    current = None
    if cert_path.exists():
        current = x509.load_pem_x509_certificate(cert_path.read_bytes())
        # An operator-installed certificate is preserved even if it expires or
        # uses a different address. Only our original self-signed issuer is managed.
        if current.subject != SUBJECT or current.issuer != SUBJECT:
            return 'custom certificate preserved'
        try:
            current.public_key().verify(current.signature, current.tbs_certificate_bytes,
                                        padding.PKCS1v15(), current.signature_hash_algorithm)
        except Exception:
            return 'custom certificate preserved'
    key = serialization.load_pem_private_key(key_path.read_bytes(), password=None) if key_path.exists() else None
    if current and key is None:
        raise ValueError('Existing certificate has no private key; restore the key before updating HTTPS')
    if key is None:
        key = rsa.generate_private_key(public_exponent=65537, key_size=3072)
        atomic(key_path, key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                         serialization.NoEncryption()), 0o600)
    if current:
        if current.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo) != key.public_key().public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo):
            raise ValueError('Certificate and private key do not match')
        try:
            covered = set(current.extensions.get_extension_for_class(x509.SubjectAlternativeName).value)
        except x509.ExtensionNotFound:
            covered = set()
        if set(names).issubset(covered) and current.not_valid_after_utc > datetime.now(timezone.utc) + timedelta(days=30):
            return 'certificate already current'
    moment = datetime.now(timezone.utc)
    certificate = (x509.CertificateBuilder().subject_name(SUBJECT).issuer_name(SUBJECT)
        .public_key(key.public_key()).serial_number(x509.random_serial_number())
        .not_valid_before(moment - timedelta(minutes=5)).not_valid_after(moment + timedelta(days=365))
        .add_extension(x509.SubjectAlternativeName(names), critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        .sign(key, hashes.SHA256()))
    atomic(cert_path, certificate.public_bytes(serialization.Encoding.PEM), 0o644)
    return 'local-IP certificate updated'


def refresh_web_config(path):
    path = Path(path)
    source = path.read_text()
    header = '    add_header Cache-Control "no-cache, max-age=0, must-revalidate" always;\n'
    if 'root /opt/airlink/frontend/build/web;' in source and 'add_header Cache-Control' not in source:
        source = source.replace('    root /opt/airlink/frontend/build/web;', header + '    root /opt/airlink/frontend/build/web;', 1)
        atomic(path, source.encode(), 0o644)
        return True
    return False


if __name__ == '__main__':
    print(ensure_certificate('/etc/airlink', local_addresses()))
    refresh_web_config('/etc/nginx/sites-available/airlink')
