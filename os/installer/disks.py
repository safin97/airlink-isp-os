"""Fail-closed disk discovery. No mutation functions live in this module."""
import hashlib
import json
import os
import re
import subprocess
from dataclasses import dataclass, asdict

MIN_BYTES = 32 * 1024 ** 3


@dataclass(frozen=True)
class Disk:
    path: str
    model: str
    serial: str
    size: int
    transport: str
    major_minor: str
    partitions: list
    blocked: list

    @property
    def identity(self):
        return hashlib.sha256(json.dumps(asdict(self), sort_keys=True).encode()).hexdigest()


def descendants(node):
    yield node
    for child in node.get("children", []):
        yield from descendants(child)


def parse_disks(data, swaps=(), held=()):
    result = []
    for node in data["blockdevices"]:
        if node.get("type") != "disk":
            continue
        children = list(descendants(node))
        blocked = []
        if node.get("ro"):
            blocked.append("Read-only disk")
        if int(node["size"]) < MIN_BYTES:
            blocked.append("At least 32 GiB required")
        for child in children:
            if any(child.get("mountpoints") or []):
                blocked.append("Mounted filesystem: " + child["path"])
            if child["path"] in swaps:
                blocked.append("Active swap: " + child["path"])
            if child["path"] in held or child.get("type") in {"crypt", "lvm", "raid", "md", "mpath"}:
                blocked.append("Active device mapping: " + child["path"])
        path = node["path"]
        if not re.fullmatch(r"/dev/(sd[a-z]+|vd[a-z]+|nvme\d+n\d+|mmcblk\d+)", path):
            blocked.append("Unsupported block-device naming")
        result.append(Disk(path, (node.get("model") or "Unknown model").strip(), node.get("serial") or "",
                           int(node["size"]), node.get("tran") or ("SSD" if not node.get("rota") else "HDD"),
                           node["maj:min"], [c["path"] for c in children[1:]], sorted(set(blocked))))
    return result


def discover():
    raw = subprocess.check_output(["lsblk", "--json", "--bytes", "--paths", "--output",
                                   "PATH,TYPE,SIZE,MODEL,SERIAL,TRAN,ROTA,RO,MOUNTPOINTS,MAJ:MIN"], text=True)
    swaps = subprocess.check_output(["swapon", "--show=NAME", "--noheadings", "--raw"], text=True).splitlines()
    held = []
    for name in os.listdir("/sys/class/block"):
        if os.listdir("/sys/class/block/" + name + "/holders"):
            held.append("/dev/" + name)
    return parse_disks(json.loads(raw), swaps, held)


def authorize(disks, path, identity, confirmation, acknowledged):
    if confirmation != "ERASE" or acknowledged is not True:
        raise ValueError("Type ERASE and acknowledge irreversible data destruction")
    matches = [d for d in disks if d.path == path]
    if len(matches) != 1:
        raise ValueError("Selected disk is no longer present")
    disk = matches[0]
    if disk.identity != identity:
        raise ValueError("Disk identity changed; select and review the disk again")
    if disk.blocked:
        raise ValueError("Protected disk: " + "; ".join(disk.blocked))
    return disk
