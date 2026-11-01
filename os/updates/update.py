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
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w") as file:
        json.dump(data, file)
        file.flush()
        os.fsync(file.fileno())
    tmp.chmod(0o600)
    tmp.replace(path)


def read(path, default):
    return json.loads(path.read_text()) if path.exists() else default


class HTTPSOnly(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urllib.parse.urlparse(newurl).scheme != "https":
            raise ValueError("Insecure update redirect rejected")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def download(url, destination, limit):
    if urllib.parse.urlparse(url).scheme != "https":
        raise ValueError("HTTPS required")
    opener = urllib.request.build_opener(HTTPSOnly())
    total = 0
    temp = destination.with_suffix(".partial")
    with opener.open(url, timeout=30) as source, open(temp, "wb") as out:
        while True:
            chunk = source.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > limit:
                raise ValueError("Download exceeds signed size")
            out.write(chunk)
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


def status():
    return {"configured": CONFIG.exists() and KEY.exists(), "rollback_supported": False,
            "state": read(ROOT / "state.json", {"status": "idle"}),
            "available": read(ROOT / "verified.json", None)}


def action(name, payload):
    ROOT.mkdir(parents=True, exist_ok=True, mode=0o700)
    if name == "status":
        return status()
    if not CONFIG.exists() or not KEY.exists():
        raise ValueError("No trusted release source is configured. Install the publisher public key locally.")
    with open(ROOT / "lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if name == "check":
            config = read(CONFIG, {})
            download(config["manifest_url"], ROOT / "manifest.json", 128 * 1024)
            meta = manifest()
            atomic(ROOT / "verified.json", meta)
            return meta
        meta = manifest()
        if name == "download":
            download(meta["url"], ROOT / "package.deb", meta["size"])
            verify_package(meta)
        elif name == "verify":
            verify_package(meta)
        elif name in ("install", "schedule"):
            verify_package(meta)
            if name == "schedule":
                at = datetime.fromisoformat(payload["at"].replace("Z", "+00:00"))
                if at.tzinfo is None or at <= datetime.now(timezone.utc):
                    raise ValueError("Schedule must be in the future with timezone")
                when = at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
                timer = Path("/etc/systemd/system/airlink-update-job.timer")
                timer.write_text("[Unit]\nDescription=Scheduled AirLink update\n[Timer]\nOnCalendar=" + when +
                                 "\nPersistent=true\nUnit=airlink-update-job.service\n[Install]\nWantedBy=timers.target\n")
                timer.chmod(0o644)
                subprocess.run(["systemctl", "daemon-reload"], check=True)
                subprocess.run(["systemctl", "enable", "--now", "airlink-update-job.timer"], check=True)
            else:
                subprocess.run(["systemctl", "start", "--no-block", "airlink-update-job.service"], check=True)
        else:
            raise ValueError("Unsupported update action")
        return {"version": meta["version"], "status": name}


def install():
    ROOT.mkdir(parents=True, exist_ok=True)
    with open(ROOT / "lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        previous = read(ROOT / "state.json", {})
        if previous.get("status") in {"installing", "failed"}:
            raise RuntimeError("Interrupted/failed update requires local recovery review")
        meta = manifest()
        verify_package(meta)
        if shutil.disk_usage("/").free < meta["size"] * 3 + 1024**3:
            raise RuntimeError("Insufficient update/backup space")
        subprocess.run(["/bin/bash", "/opt/airlink/deployment/health.sh"], check=True)
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
