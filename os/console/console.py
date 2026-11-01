import getpass
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
import httpx
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
from airlink.api import broker
from airlink import __version__

BASE = "http://127.0.0.1:8000"


def api(method, path, **kwargs):
    response = httpx.request(method, BASE + path, timeout=15, **kwargs)
    response.raise_for_status()
    return response.json()


def network():
    print(json.dumps(broker("network.status"), indent=2))
    interface = input("Network interface: ").strip()
    method = input("DHCP or static [dhcp]: ").strip().lower() or "dhcp"
    data = {"interface": interface, "method": method, "hostname": input("Hostname [airlink]: ").strip() or "airlink"}
    if method == "static":
        data.update(address=input("IP address: ").strip(), prefix=int(input("Subnet prefix [24]: ") or "24"),
                    gateway=input("Gateway: ").strip(), dns=[x.strip() for x in input("DNS servers (comma separated): ").split(",")])
    broker("network.save", data)
    if input("Apply these settings? Type APPLY: ") != "APPLY":
        return
    result = broker("network.apply", data)
    print("The previous configuration will return in 120 seconds unless confirmed.")
    print(json.dumps(broker("network.status"), indent=2))
    if input("Keep new configuration? Type KEEP: ") == "KEEP":
        print(broker("network.confirm", {"checkpoint": result["checkpoint"]}))
    else:
        print(broker("network.restore", {"checkpoint": result["checkpoint"]}))


def firstboot():
    print("\nAIRLINK ISP OS — First boot setup\n")
    print("DHCP is active by default. Configure static addressing now or later.")
    if input("Open network settings? [y/N]: ").lower() == "y":
        network()
    token = os.environ.get("AIRLINK_BOOTSTRAP_TOKEN", "")
    if not token:
        for line in Path("/etc/airlink/airlink.env").read_text().splitlines():
            if line.startswith("AIRLINK_BOOTSTRAP_TOKEN="):
                token = line.split("=", 1)[1]
    print("Create the first owner. No default password exists.")
    username = input("Username: ").strip()
    password = getpass.getpass("Password (14–128 characters): ")
    confirm = getpass.getpass("Confirm password: ")
    api("POST", "/api/setup", json={"username": username, "password": password, "confirm_password": confirm, "token": token})
    print("Owner created. Sign in from this console or the HTTPS dashboard.")


def authenticate():
    login = api("POST", "/api/auth/login", json={"username": input("Owner username: ").strip(), "password": getpass.getpass("Password: ")})
    if login["user"]["role"] != "owner":
        raise ValueError("Owner authentication required for local administration")
    return login["access_token"]


def main():
    while True:
        try:
            print("\033[2J\033[H", end="")
            print(f"  AIRLINK ISP OS  |  {__version__}  |  {socket.gethostname()}\n")
            try:
                status = broker("status")
                print(f"CPU {status['cpu_percent']}%   RAM {status['memory_percent']}%   Storage {status['storage_percent']}%")
                for interface in status["addresses"]:
                    for address in interface.get("addr_info", []):
                        if address.get("scope") == "global":
                            print("Dashboard: https://" + address["local"] + "  (" + interface["ifname"] + ")")
                print("\n" + "  |  ".join(k + ": " + v for k, v in status["services"].items()))
            except Exception:
                print("System controller is starting or unavailable.")
            try:
                if not api("GET", "/api/setup/status")["initialized"]:
                    firstboot()
                    continue
            except httpx.HTTPError:
                print("API is starting or unavailable. Retrying in 5 seconds.")
                time.sleep(5)
                continue
            print("\n1 Network Settings   2 Service Status   3 Software Updates\n4 Backup and Restore  5 System Logs      6 Restart Services\n7 Reboot              8 Shutdown         9 Recovery\n0 Refresh")
            choice = input("Select: ").strip()
            if choice == "0":
                continue
            if choice not in set("123456789"):
                continue
            token = authenticate()
            # Every administrative action requires fresh owner authentication.
            if choice == "1":
                network()
            elif choice == "2":
                print(json.dumps(broker("status"), indent=2))
            elif choice == "3":
                print(json.dumps(broker("updates.status"), indent=2))
                action = input("check / download / verify / install (blank to return): ")
                if action in {"check", "download", "verify", "install"}:
                    print(api("POST", "/api/updates/" + action, json={}, headers={"Authorization": "Bearer " + token}))
            elif choice == "4":
                mode = input("backup or restore: ")
                if mode == "backup":
                    subprocess.run(["bash", "/opt/airlink/os/recovery/backup.sh"], check=True)
                elif mode == "restore":
                    print("\n".join(str(x) for x in Path("/var/backups/airlink").iterdir()))
                    path = input("Backup directory: ")
                    confirmation = input("Type RESTORE to replace the database: ")
                    subprocess.run(["bash", "/opt/airlink/os/recovery/restore.sh", path, confirmation], check=True)
            elif choice == "5":
                subprocess.run(["journalctl", "--no-pager", "-n", "100", "-u", "airlink-api", "-u", "airlink-monitor", "-u", "airlink-update-job"])
            elif choice == "6":
                subprocess.run(["systemctl", "restart", "airlink-api", "airlink-monitor", "airlink-alerts", "nginx"], check=True)
            elif choice in ("7", "8"):
                verb = "reboot" if choice == "7" else "poweroff"
                if input("Type " + verb.upper() + " to confirm: ") == verb.upper():
                    subprocess.run(["systemctl", verb], check=True)
            elif choice == "9":
                print(Path("/opt/airlink/docs/RECOVERY.md").read_text())
            input("Press Enter to return to the console.")
        except (Exception, KeyboardInterrupt) as exc:
            print("Action failed:", str(exc))
            time.sleep(3)


if __name__ == "__main__":
    main()
