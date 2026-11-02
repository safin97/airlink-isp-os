"""Signed, owner-triggered Debian package updates. No remote script execution."""
import base64
import fcntl
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
import tempfile
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

ROOT = Path("/var/lib/airlink-system/updates")
CONFIG = Path("/etc/airlink/update-source.json")
KEY = Path("/etc/airlink/update-public-key.bin")
MAX_PACKAGE = 2 * 1024 ** 3


def canonical(manifest):
    return json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()


def verify_manifest(envelope, public_key, current_sequence=0):
    manifest = envelope["manifest"]
    Ed25519PublicKey.from_public_bytes(public_key).verify(base64.b64decode(envelope["signature"], validate=True), canonical(manifest))
    required = {"version", "sequence", "sha256", "size", "url", "expires", "release_notes", "reboot_required"}
    if set(manifest) != required:
        raise ValueError("Unexpected manifest fields")
    if not re.fullmatch(r"[0-9][A-Za-z0-9.+~-]{0,39}", manifest["version"]):
        raise ValueError("Invalid version")
    if type(manifest["sequence"]) is not int or manifest["sequence"] <= current_sequence:
        raise ValueError("Update replay/downgrade rejected")
    if not re.fullmatch(r"[a-f0-9]{64}", manifest["sha256"]):
        raise ValueError("Invalid package digest")
    if type(manifest["size"]) is not int or not 1 <= manifest["size"] <= MAX_PACKAGE:
        raise ValueError("Invalid package size")
    expires = datetime.fromisoformat(manifest["expires"].replace("Z", "+00:00"))
    if expires.tzinfo is None or expires <= datetime.now(timezone.utc):
        raise ValueError("Update manifest expired")
    url = urllib.parse.urlparse(manifest["url"])
    if url.scheme != "https" or not url.hostname or url.username or url.password:
        raise ValueError("Update package must use HTTPS")
    return manifest


def atomic(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".update-", dir=path.parent)
    tmp = Path(name)
    try:
        with os.fdopen(fd, "w") as file:
            json.dump(data, file)
            file.flush()
            os.fsync(file.fileno())
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)


def read(path, default):
    return json.loads(path.read_text()) if path.exists() else default


class HTTPSOnly(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urllib.parse.urlparse(newurl).scheme != "https":
            raise ValueError("Insecure update redirect rejected")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def download(url, destination, limit, progress=None):
    if urllib.parse.urlparse(url).scheme != "https":
        raise ValueError("HTTPS required")
    opener = urllib.request.build_opener(HTTPSOnly())
    total = 0
    last_progress = 0
    temp = destination.with_suffix(".partial")
    request = urllib.request.Request(url, headers={"Cache-Control": "no-cache", "Pragma": "no-cache"})
    with opener.open(request, timeout=30) as source, open(temp, "wb") as out:
        while True:
            chunk = source.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > limit:
                raise ValueError("Download exceeds signed size")
            out.write(chunk)
            if progress and (time.monotonic() - last_progress >= 0.5 or total == limit):
                progress(total, limit)
                last_progress = time.monotonic()
        out.flush()
        os.fsync(out.fileno())
    temp.replace(destination)


def manifest():
    envelope = read(ROOT / "manifest.json", {})
    seq = read(ROOT / "installed.json", {"sequence": 0})["sequence"]
    return verify_manifest(envelope, KEY.read_bytes(), seq)


def verify_package(meta):
    package = ROOT / "package.deb"
    if package.stat().st_size != meta["size"]:
        raise ValueError("Package size mismatch")
    sha = hashlib.sha256()
    with open(package, "rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            sha.update(block)
    if sha.hexdigest() != meta["sha256"]:
        raise ValueError("Package digest mismatch")
    info = subprocess.check_output(["dpkg-deb", "-f", str(package), "Package", "Architecture", "Version"], text=True)
    fields = dict(line.split(": ", 1) for line in info.strip().splitlines())
    if fields != {"Package": "airlink-isp-os", "Architecture": "amd64", "Version": meta["version"]}:
        raise ValueError("Unexpected package identity")


def restart_status():
    try:
        boot_id = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
    except OSError:
        boot_id = None
    requested = read(ROOT / 'restart.json', {})
    return {'boot_id': boot_id, 'pending': bool(boot_id and requested.get('boot_id') == boot_id)}


def restart_system(payload, *, poweroff=False):
    if payload.get('confirm') is not True:
        raise ValueError('Confirm the system restart first')
    ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
    with open(ROOT / 'lock', 'w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('An update operation is active. Wait before restarting.') from None
        if read(ROOT / 'state.json', {}).get('status') in {'queued', 'installing', 'failed'}:
            raise ValueError('An active or failed installation requires review before restarting')
        status = restart_status()
        if not status['boot_id']:
            raise ValueError('System restart is only available on the AirLink Linux appliance')
        if status['pending']:
            raise ValueError('A system restart has already been requested')
        atomic(ROOT / 'restart.json', {'boot_id': status['boot_id'], 'requested_at': time.time()})
        try:
            # A fixed, delayed systemd action allows the HTTP response/audit to finish.
            subprocess.run(['systemd-run', '--unit=airlink-system-restart', '--on-active=5s',
                            '/usr/bin/systemctl', 'poweroff' if poweroff else 'reboot'], check=True, capture_output=True, text=True)
        except Exception:
            (ROOT / 'restart.json').unlink(missing_ok=True)
            raise
        return {'status': 'restart_requested', 'boot_id': status['boot_id'], 'delay_seconds': 5}


def status():
    installed = read(ROOT / "installed.json", {"sequence": 0})
    available = read(ROOT / "verified.json", None)
    if available and available["sequence"] <= installed["sequence"]:
        available = None
    return {"configured": CONFIG.exists() and KEY.exists(), "rollback_supported": False,
            "install_supported": True, "restart_supported": True, "restart": restart_status(),
            "state": read(ROOT / "state.json", {"status": "idle"}),
            "transfer": read(ROOT / "transfer.json", {}),
            "last_check": read(ROOT / "check.json", None),
            "available": available}


def check_release():
    candidate = ROOT / "candidate.json"
    try:
        download(read(CONFIG, {})["manifest_url"], candidate, 128 * 1024)
        installed = read(ROOT / "installed.json", {"sequence": 0})
        seq = installed["sequence"]
        meta = verify_manifest(read(candidate, {}), KEY.read_bytes(), max(0, seq - 1))
        if meta["sequence"] == seq:
            if any(meta[field] != installed[field] for field in ("version", "sha256", "size")):
                raise ValueError("Published release conflicts with the installed sequence")
            (ROOT / "verified.json").unlink(missing_ok=True)
            atomic(ROOT / "check.json", {"at": time.time(), "up_to_date": True})
            return {"version": meta["version"], "up_to_date": True}
        candidate.replace(ROOT / "manifest.json")
        atomic(ROOT / "verified.json", meta)
        atomic(ROOT / "check.json", {"at": time.time(), "up_to_date": False})
        return meta
    except Exception as exc:
        atomic(ROOT / "check.json", {"at": time.time(), "error": str(exc)})
        raise
    finally:
        candidate.unlink(missing_ok=True)


def action(name, payload):
    ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
    if name == "status":
        return status()
    if not CONFIG.exists() or not KEY.exists():
        raise ValueError("No trusted release source is configured. Install the publisher public key locally.")
    with open(ROOT / "lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if name == "check":
            return check_release()
        if restart_status()['pending']:
            raise ValueError('A system restart is pending. Wait for the server to return.')
        meta = manifest()
        if any(field in payload and payload[field] != meta[field] for field in ("version", "sequence")):
            raise ValueError("Release changed. Check again before updating.")
        if name == "download":
            def progress(received, total):
                atomic(ROOT / "transfer.json", {"status": "downloading", "version": meta["version"],
                       "sequence": meta["sequence"], "received": received, "total": total})
            progress(0, meta["size"])
            try:
                download(meta["url"], ROOT / "package.deb", meta["size"], progress=progress)
                verify_package(meta)
                atomic(ROOT / "transfer.json", {"status": "verified", "version": meta["version"],
                       "sequence": meta["sequence"], "received": meta["size"], "total": meta["size"]})
            except Exception as exc:
                atomic(ROOT / "transfer.json", {"status": "failed", "error": str(exc)})
                raise
        elif name == "verify":
            verify_package(meta)
        elif name in ("install", "schedule"):
            if read(ROOT / "state.json", {}).get("status") in {"queued", "installing", "failed"}:
                raise ValueError("An active or failed installation requires local review")
            verify_package(meta)
            approved = {field: meta[field] for field in ("version", "sequence", "sha256", "size")}
            if name == "schedule":
                at = datetime.fromisoformat(payload["at"].replace("Z", "+00:00"))
                if at.tzinfo is None or at <= datetime.now(timezone.utc):
                    raise ValueError("Schedule must be in the future with timezone")
                atomic(ROOT / "request.json", approved)
                when = at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
                timer = Path("/etc/systemd/system/airlink-update-job.timer")
                timer.write_text("[Unit]\nDescription=Scheduled AirLink update\n[Timer]\nOnCalendar=" + when +
                                 "\nPersistent=true\nUnit=airlink-update-job.service\n[Install]\nWantedBy=timers.target\n")
                timer.chmod(0o644)
                subprocess.run(["systemctl", "daemon-reload"], check=True)
                subprocess.run(["systemctl", "enable", "--now", "airlink-update-job.timer"], check=True)
            else:
                atomic(ROOT / "request.json", approved)
                previous = read(ROOT / "state.json", {"status": "idle"})
                atomic(ROOT / "state.json", {"status": "queued", "version": meta["version"]})
                try:
                    subprocess.run(["systemctl", "start", "--no-block", "airlink-update-job.service"], check=True)
                except Exception:
                    atomic(ROOT / "state.json", previous)
                    raise
        else:
            raise ValueError("Unsupported update action")
        return {"version": meta["version"], "status": name}


def install():
    ROOT.mkdir(parents=True, exist_ok=True)
    with open(ROOT / "lock", "w") as lock:
        # The queued service may start before its controller request releases this lock.
        fcntl.flock(lock, fcntl.LOCK_EX)
        if restart_status()['pending']:
            raise RuntimeError('A system restart is pending; installation has not started')
        previous = read(ROOT / "state.json", {})
        if previous.get("status") in {"installing", "failed"}:
            raise RuntimeError("Interrupted/failed update requires local recovery review")
        try:
            meta = manifest()
            approved = read(ROOT / "request.json", None)
            if approved and any(meta[field] != approved[field] for field in ("version", "sequence", "sha256", "size")):
                raise ValueError("Prepared release changed after approval. Check and approve it again.")
            verify_package(meta)
            if shutil.disk_usage("/").free < meta["size"] * 3 + 1024**3:
                raise RuntimeError("Insufficient update/backup space")
            subprocess.run(["/bin/bash", "/opt/airlink/deployment/health.sh"], check=True)
        except Exception as exc:
            atomic(ROOT / "state.json", {"status": "rejected", "error": str(exc),
                   "finished": time.time(), "recovery_required": False})
            raise
        atomic(ROOT / "state.json", {"status": "installing", "version": meta["version"], "started": time.time()})
        try:
            subprocess.run(["systemctl", "stop", "airlink-api", "airlink-monitor", "airlink-alerts"], check=True)
            subprocess.run(["/bin/bash", "/opt/airlink/os/recovery/backup.sh"], check=True)
            subprocess.run(["dpkg", "--install", str(ROOT / "package.deb")], check=True)
            subprocess.run(["/bin/bash", "/opt/airlink/deployment/migrate.sh"], check=True)
            subprocess.run(["systemctl", "daemon-reload"], check=True)
            subprocess.run(["systemctl", "start", "airlink-api", "airlink-monitor", "airlink-alerts"], check=True)
            subprocess.run(["/bin/bash", "/opt/airlink/deployment/health.sh"], check=True)
            atomic(ROOT / "installed.json", meta)
            atomic(ROOT / "state.json", {"status": "installed", "version": meta["version"], "finished": time.time(), "reboot_required": meta["reboot_required"]})
        except Exception as exc:
            atomic(ROOT / "state.json", {"status": "failed", "version": meta["version"], "error": str(exc), "recovery_required": True})
            raise


if __name__ == "__main__":
    if sys.argv[1:] != ["install"] or os.geteuid() != 0:
        sys.exit("Usage: root only: update.py install")
    install()
