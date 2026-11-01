"""Root Unix socket, peer-credential checked, fixed allowlist; no shell payloads."""
import json
import os
import pwd
import socket
import socketserver
import struct
import subprocess
import sys
from pathlib import Path
import psutil
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from network.configure import action as network_action
from updates.update import action as update_action

SOCKET = Path("/run/airlink/control.sock")


def status():
    services = {}
    for name in ("postgresql", "redis-server", "airlink-api", "airlink-monitor", "airlink-alerts", "nginx"):
        services[name] = subprocess.run(["systemctl", "is-active", name], capture_output=True, text=True).stdout.strip()
    return {"hostname": socket.gethostname(), "cpu_percent": psutil.cpu_percent(interval=0.2),
            "memory_percent": psutil.virtual_memory().percent, "storage_percent": psutil.disk_usage("/").percent,
            "addresses": json.loads(subprocess.check_output(["ip", "-j", "address"], text=True)), "services": services}


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
    SOCKET.parent.mkdir(exist_ok=True)
    SOCKET.unlink(missing_ok=True)
    with socketserver.ThreadingUnixStreamServer(str(SOCKET), Handler) as server:
        os.chown(SOCKET, 0, pwd.getpwnam("airlink").pw_gid)
        SOCKET.chmod(0o660)
        server.serve_forever()
