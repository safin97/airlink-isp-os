import importlib.util
from pathlib import Path
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.x509.oid import NameOID

spec=importlib.util.spec_from_file_location('dashboard_https',Path(__file__).resolve().parents[1]/'deployment/dashboard_https.py')
https=importlib.util.module_from_spec(spec);spec.loader.exec_module(https)


def test_local_ip_certificate_idempotent_and_preserves_key(tmp_path):
    assert https.ensure_certificate(tmp_path,{'127.0.0.1','192.168.10.2'})=='local-IP certificate updated'
    private=(tmp_path/'tls.key').read_bytes()
    certificate=(tmp_path/'tls.crt').read_bytes()
    parsed=x509.load_pem_x509_certificate(certificate)
    names=parsed.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    assert '192.168.10.2' in [str(ip) for ip in names.get_values_for_type(x509.IPAddress)]
    assert (tmp_path/'tls.key').stat().st_mode & 0o777 == 0o600
    assert https.ensure_certificate(tmp_path,{'192.168.10.2'})=='certificate already current'
    assert (tmp_path/'tls.crt').read_bytes()==certificate
    assert https.ensure_certificate(tmp_path,{'192.168.20.2'})=='local-IP certificate updated'
    assert (tmp_path/'tls.key').read_bytes()==private


def test_operator_certificate_is_preserved(tmp_path,monkeypatch):
    original=https.SUBJECT
    monkeypatch.setattr(https,'SUBJECT',x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'dashboard.example.com')]))
    https.ensure_certificate(tmp_path,{'192.168.10.2'})
    certificate=(tmp_path/'tls.crt').read_bytes()
    monkeypatch.setattr(https,'SUBJECT',original)
    assert https.ensure_certificate(tmp_path,{'192.168.20.2'})=='custom certificate preserved'
    assert (tmp_path/'tls.crt').read_bytes()==certificate


def test_cache_policy_preserves_existing_https_configuration(tmp_path):
    path=tmp_path/'airlink'
    path.write_text('server {\n    ssl_certificate /custom/domain.crt;\n    root /opt/airlink/frontend/build/web;\n}\n')
    assert https.refresh_web_config(path)
    assert 'ssl_certificate /custom/domain.crt;' in path.read_text()
    assert 'no-cache, max-age=0, must-revalidate' in path.read_text()
    assert not https.refresh_web_config(path)
