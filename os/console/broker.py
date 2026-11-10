"""Root Unix socket, peer-credential checked, fixed allowlist; no shell payloads."""
import json
import os
import pwd
import socket
import socketserver
import struct
import subprocess
import sys
import re
from pathlib import Path
import psutil
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from network.configure import action as network_action
from updates.update import action as update_action, restart_system
from console.gpu import detect as detect_gpus
from cloud_backups.service import service as drive_backup_service

SOCKET = Path("/run/airlink/control.sock")


def status():
    services = {}
    for name in ("postgresql", "redis-server", "airlink-api", "airlink-monitor", "airlink-alerts", "nginx"):
        services[name] = subprocess.run(["systemctl", "is-active", name], capture_output=True, text=True).stdout.strip()
    return {"hostname": socket.gethostname(), "cpu_percent": psutil.cpu_percent(interval=0.2),
            "memory_percent": psutil.virtual_memory().percent, "storage_percent": psutil.disk_usage("/").percent,
            "addresses": json.loads(subprocess.check_output(["ip", "-j", "address"], text=True)),
            "services": services, "gpus": detect_gpus()}


def diagnostics():
    system = status()
    update_state = update_action("status", {}).get("state", {})
    problems = []
    for name, value in system["services"].items():
        if value != "active":
            problems.append({"severity": "critical", "source": "service",
                             "title": name + " is " + (value or "unknown"),
                             "detail": "Review this service before retrying maintenance or updates."})
    for key, label, warning, critical in (
        ("storage_percent", "Storage", 80, 92),
        ("memory_percent", "Memory", 85, 95),
        ("cpu_percent", "CPU", 90, 98),
    ):
        value = float(system.get(key, 0) or 0)
        if value >= warning:
            problems.append({"severity": "critical" if value >= critical else "warning",
                             "source": "system", "title": f"{label} usage is {value:.1f}%",
                             "detail": f"{label} usage crossed the {warning}% warning threshold."})
    if update_state.get("status") in {"failed", "installing"}:
        problems.append({"severity": "critical", "source": "update",
                         "title": "Software update requires local recovery review",
                         "detail": str(update_state.get("error") or
                                       "The installation did not finish cleanly."),
                         "recovery_required": bool(update_state.get("recovery_required", True))})
    units = ["airlink-api", "airlink-monitor", "airlink-alerts", "airlink-controller",
             "airlink-update-job", "nginx", "postgresql", "redis-server"]
    command = ["journalctl", "--no-pager", "--priority=err..alert", "-n", "100",
               "--output=short-iso", *sum((["-u", unit] for unit in units), [])]
    journal = subprocess.run(command, capture_output=True, text=True, timeout=10).stdout
    secret = re.compile(r"(?i)(password|token|secret|community|authorization)([=:\s]+)([^\s,;]+)")
    errors = [secret.sub(r"\1\2[redacted]", line)[:500] for line in journal.splitlines()
              if line.strip() and "-- No entries --" not in line][-100:]
    return {"status": "problems" if problems else "healthy", "checked_at": __import__("time").time(),
            "problems": problems, "services": system["services"],
            "resources": {key: system[key] for key in ("cpu_percent", "memory_percent", "storage_percent")},
            "update": update_state, "recent_errors": errors}


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        _, uid, _ = struct.unpack("3i", self.connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
        if uid not in (0, pwd.getpwnam("airlink").pw_uid):
            return
        self.connection.settimeout(10)
        try:
            raw = self.rfile.readline(65537)
            if len(raw) > 65536:
                raise ValueError("Request too large")
            req = json.loads(raw)
            name, payload = req["action"], req.get("payload", {})
            if name == "status":
                result = status()
            elif name == "diagnostics.status":
                result = diagnostics()
            elif name == "system.restart":
                result = restart_system(payload)
            elif name.startswith("backups.google-drive."):
                result = drive_backup_service.action(name.removeprefix("backups.google-drive."), payload)
            elif name.startswith("network."):
                result = network_action(name.split(".", 1)[1], payload)
            elif name.startswith("updates."):
                result = update_action(name.split(".", 1)[1], payload)
            else:
                raise ValueError("Action not allowed")
            response = {"ok": True, "result": result}
        except Exception as exc:
            response = {"ok": False, "error": str(exc)}
        self.wfile.write(json.dumps(response).encode() + b"\n")


if __name__ == "__main__":
    Path("/var/lib/airlink-system").mkdir(mode=0o700, exist_ok=True)
    drive_backup_service.start()
    SOCKET.parent.mkdir(exist_ok=True)
    SOCKET.unlink(missing_ok=True)
    with socketserver.ThreadingUnixStreamServer(str(SOCKET), Handler) as server:
        os.chown(SOCKET, 0, pwd.getpwnam("airlink").pw_gid)
        SOCKET.chmod(0o660)
        server.serve_forever()
