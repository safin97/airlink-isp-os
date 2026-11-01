import fcntl
import os
from pathlib import Path
import subprocess
from .disks import discover, authorize

TARGET = Path("/run/airlink-target")
SOURCE = Path("/run/live/medium/live/filesystem.squashfs")


def partition_path(disk, number):
    return disk + ("p" if disk[-1].isdigit() else "") + str(number)


def run(argv, emit, **kwargs):
    emit("$ " + " ".join(argv))
    proc = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, **kwargs)
    for line in proc.stdout:
        emit(line.rstrip())
    if proc.wait():
        raise RuntimeError("Command failed: " + argv[0])


def install(path, identity, confirmation, acknowledged, emit=print):
    if os.geteuid() != 0 or not SOURCE.is_file() or not Path("/sys/firmware/efi").is_dir():
        raise RuntimeError("Installation requires root in the UEFI-booted AirLink live image")
    lock = open("/run/airlink-installer.lock", "w")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    mounts = []
    try:
        disk = authorize(discover(), path, identity, confirmation, acknowledged)
        # Pin an exclusive handle and recheck immediately before the first destructive command.
        fd = os.open(disk.path, os.O_RDONLY | os.O_EXCL)
        try:
            authorize(discover(), path, identity, confirmation, acknowledged)
            emit("[1/8] Partitioning selected disk " + path)
            run(["sgdisk", "--zap-all", "--new=1:0:+512M", "--typecode=1:ef00", "--change-name=1:AirLink EFI",
                 "--new=2:0:0", "--typecode=2:8300", "--change-name=2:AirLink System", path], emit)
        finally:
            os.close(fd)
        run(["partprobe", path], emit)
        run(["udevadm", "settle"], emit)
        efi, root = partition_path(path, 1), partition_path(path, 2)
        run(["mkfs.vfat", "-F", "32", "-n", "AIRLINKEFI", efi], emit)
        run(["mkfs.ext4", "-F", "-L", "AIRLINKROOT", root], emit)
        TARGET.mkdir(mode=0o700, exist_ok=True)
        run(["mount", root, str(TARGET)], emit)
        mounts.append(TARGET)
        emit("[2/8] Installing the complete offline system image")
        run(["unsquashfs", "-f", "-no-progress", "-d", str(TARGET), str(SOURCE)], emit)
        (TARGET / "boot/efi").mkdir(parents=True, exist_ok=True)
        run(["mount", efi, str(TARGET / "boot/efi")], emit)
        mounts.append(TARGET / "boot/efi")
        for name in ("dev", "proc", "sys"):
            run(["mount", "--rbind", "/" + name, str(TARGET / name)], emit)
            run(["mount", "--make-rslave", str(TARGET / name)], emit)
            mounts.append(TARGET / name)
        emit("[3/8] Configuring filesystem and host identity")
        uuid_root = subprocess.check_output(["blkid", "-s", "UUID", "-o", "value", root], text=True).strip()
        uuid_efi = subprocess.check_output(["blkid", "-s", "UUID", "-o", "value", efi], text=True).strip()
        (TARGET / "etc/fstab").write_text(f"UUID={uuid_root} / ext4 defaults,noatime 0 1\nUUID={uuid_efi} /boot/efi vfat umask=0077 0 2\n")
        (TARGET / "etc/machine-id").write_text("")
        (TARGET / "etc/hostname").write_text("airlink\n")
        (TARGET / "etc/airlink/installed").touch()
        (TARGET / "etc/default/grub").write_text('GRUB_DEFAULT=0\nGRUB_TIMEOUT=5\nGRUB_DISTRIBUTOR="AirLink ISP OS"\nGRUB_CMDLINE_LINUX_DEFAULT="quiet"\nGRUB_DISABLE_OS_PROBER=true\n')
        emit("[4/8] Initializing database, credentials, TLS and services")
        run(["chroot", str(TARGET), "/bin/bash", "/opt/airlink/deployment/provision.sh"], emit)
        emit("[5/8] Building hardware initramfs")
        run(["chroot", str(TARGET), "update-initramfs", "-u", "-k", "all"], emit)
        emit("[6/8] Installing UEFI bootloader on the selected disk")
        run(["chroot", str(TARGET), "grub-install", "--target=x86_64-efi", "--efi-directory=/boot/efi",
             "--bootloader-id=AirLink", "--no-nvram", "--removable"], emit)
        run(["chroot", str(TARGET), "update-grub"], emit)
        emit("[7/8] Verifying installed components")
        run(["chroot", str(TARGET), "/bin/bash", "/opt/airlink/deployment/verify.sh"], emit)
        if not (TARGET / "boot/efi/EFI/BOOT/BOOTX64.EFI").is_file():
            raise RuntimeError("UEFI bootloader missing")
        emit("[8/8] Synchronizing filesystems")
        run(["sync"], emit)
    finally:
        cleanup_failed = False
        for mount in reversed(mounts):
            result = subprocess.run(["umount", "-R", str(mount)], capture_output=True, text=True)
            if result.returncode:
                cleanup_failed = True
                emit("Unmount failed: " + result.stderr)
        lock.close()
        if cleanup_failed:
            raise RuntimeError("Target filesystems could not be safely unmounted; installation completion is not verified")
    emit("INSTALLATION VERIFIED — remove USB before restarting")
