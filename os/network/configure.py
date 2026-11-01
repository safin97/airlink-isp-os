import ipaddress
import json
import re
import socket
import subprocess
import time
import uuid
from pathlib import Path

STATE = Path("/var/lib/airlink-system/network.json")
PENDING = Path("/run/airlink/network-pending.json")


def validate(data):
    allowed = {"interface", "method", "address", "prefix", "gateway", "dns", "hostname"}
    if set(data) - allowed:
        raise ValueError("Unknown network setting")
    interface = str(data.get("interface", ""))
    if not re.fullmatch(r"[a-zA-Z0-9_.:-]{1,15}", interface) or interface == "lo":
        raise ValueError("Select a physical network interface")
    hostname = str(data.get("hostname", "airlink"))
    if not re.fullmatch(r"[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?", hostname):
        raise ValueError("Use a valid single-label hostname")
    result = {"interface": interface, "method": data.get("method"), "hostname": hostname}
    if result["method"] == "dhcp":
        return result
    if result["method"] != "static":
        raise ValueError("Choose DHCP or static")
    subnet = ipaddress.ip_interface(f"{data.get('address')}/{int(data.get('prefix', 24))}")
    if subnet.version != 4 or not 1 <= subnet.network.prefixlen <= 30:
        raise ValueError("Static IPv4 prefix must be 1–30")
    if subnet.ip in (subnet.network.network_address, subnet.network.broadcast_address) or subnet.ip.is_loopback or subnet.ip.is_multicast or subnet.ip.is_link_local:
        raise ValueError("Invalid host address")
    gateway = ipaddress.ip_address(data.get("gateway", ""))
    if gateway not in subnet.network or gateway in (subnet.ip, subnet.network.network_address, subnet.network.broadcast_address):
        raise ValueError("Gateway must be a different host in the selected subnet")
    dns = data.get("dns", [])
    if not isinstance(dns, list) or not 1 <= len(dns) <= 2:
        raise ValueError("Provide one or two DNS servers")
    servers = [ipaddress.ip_address(s) for s in dns]
    if any(s.is_unspecified or s.is_multicast for s in servers):
        raise ValueError("Invalid DNS server")
    result.update(address=str(subnet.ip), prefix=subnet.network.prefixlen, gateway=str(gateway), dns=[str(s) for s in servers])
    return result


def run(args):
    return subprocess.check_output(args, text=True, stderr=subprocess.STDOUT, timeout=25).strip()


def nm():
    import dbus
    return dbus.Interface(dbus.SystemBus().get_object("org.freedesktop.NetworkManager", "/org/freedesktop/NetworkManager"), "org.freedesktop.NetworkManager")


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(value))
    temp.chmod(0o600)
    temp.replace(path)


def status():
    return {"interfaces": run(["nmcli", "-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device"]),
            "addresses": json.loads(run(["ip", "-j", "address"])),
            "saved": json.loads(STATE.read_text()) if STATE.exists() else None,
            "pending": json.loads(PENDING.read_text()) if PENDING.exists() else None}


def action(name, data):
    if name == "status":
        return status()
    if name == "save":
        value = validate(data)
        write(STATE, value)
        return {"saved": True}
    if name == "apply":
        value = validate(data or json.loads(STATE.read_text()))
        if not Path("/sys/class/net", value["interface"]).exists():
            raise ValueError("Interface not found")
        manager = nm()
        device = manager.GetDeviceByIpIface(value["interface"])
        # NM owns the timer, so rollback survives an API or broker crash.
        checkpoint = str(manager.CheckpointCreate([device], 120, 2))
        connection = "airlink-" + str(uuid.uuid4())
        write(PENDING, {"checkpoint": checkpoint, "connection": connection, "settings": value, "deadline": time.time() + 120})
        try:
            args = ["nmcli", "connection", "add", "type", "ethernet", "ifname", value["interface"],
                    "con-name", connection, "connection.autoconnect", "no", "connection.autoconnect-priority", "100",
                    "ipv4.method", "auto" if value["method"] == "dhcp" else "manual"]
            if value["method"] == "static":
                args += ["ipv4.addresses", f"{value['address']}/{value['prefix']}", "ipv4.gateway", value["gateway"],
                         "ipv4.dns", ",".join(value["dns"])]
            run(args)
            # Async activation keeps the request responsive while the address changes.
            run(["nmcli", "--wait", "0", "connection", "up", connection])
        except Exception:
            manager.CheckpointRollback(checkpoint)
            PENDING.unlink(missing_ok=True)
            raise
        return {"checkpoint": checkpoint, "rollback_seconds": 120, "message": "Confirm from the new address within 120 seconds"}
    if name in ("confirm", "restore"):
        if not PENDING.exists():
            raise ValueError("No pending configuration")
        pending = json.loads(PENDING.read_text())
        if data.get("checkpoint") != pending["checkpoint"]:
            raise ValueError("Checkpoint does not match")
        if name == "confirm":
            if time.time() >= pending["deadline"]:
                PENDING.unlink(missing_ok=True)
                raise ValueError("Confirmation expired; NetworkManager rolled back")
            nm().CheckpointDestroy(pending["checkpoint"])
            # An unconfirmed profile must never take over after a power loss.
            run(["nmcli", "connection", "modify", pending["connection"], "connection.autoconnect", "yes"])
            run(["hostnamectl", "set-hostname", pending["settings"]["hostname"]])
            write(STATE, pending["settings"])
        else:
            nm().CheckpointRollback(pending["checkpoint"])
        PENDING.unlink(missing_ok=True)
        return {"confirmed": name == "confirm"}
    if name == "test":
        target = str(ipaddress.ip_address(data.get("address", "1.1.1.1")))
        return {"result": run(["ping", "-n", "-c", "2", "-W", "2", target])}
    if name == "dns":
        host = data.get("hostname", "debian.org")
        if not re.fullmatch(r"[a-zA-Z0-9.-]{1,253}", host):
            raise ValueError("Invalid DNS name")
        return {"result": run(["getent", "ahosts", host])}
    raise ValueError("Unknown network action")
