"""Offer missing GTX 1660 Ti drivers through the existing reviewed APT plan.

Detection and planning only: this module never adds repositories, installs
packages, changes GPU clocks, unloads drivers or restarts the display.
"""
import platform
import re

from console.gpu import detect

TARGET = '0x2191'
VERSION = r'[0-9][A-Za-z0-9.+:~\-]*'


def missing_driver_plan(run):
    nvidia = [gpu for gpu in detect() if gpu['vendor_id'] == '0x10de']
    if not any(gpu['device_id'] == TARGET for gpu in nvidia):
        return None
    result = {'targets': [], 'message': '', 'kernel': None}
    if any(gpu['device_id'] != TARGET for gpu in nvidia):
        result['message'] = 'Multiple NVIDIA models detected. Review driver compatibility locally before installing a new driver.'
        return result
    if all(gpu['status'] == 'ready' for gpu in nvidia):
        result['message'] = 'GTX 1660 Ti: NVIDIA driver is responding. Local display acceleration is shown in PC settings → Overview.'
        return result
    if platform.machine() not in {'x86_64', 'amd64'}:
        result['message'] = 'GTX 1660 Ti driver installation requires an amd64 AirLink PC.'
        return result

    # Preserve an existing driver family/branch, even if it cannot load. A
    # module-signing or hardware failure must not trigger a driver replacement.
    for package in ('nvidia-open', 'cuda-drivers', 'nvidia-driver',
                    'nvidia-kernel-dkms', 'nvidia-open-kernel-dkms', 'nvidia-kernel-open-dkms'):
        installed = run(['dpkg-query', '-W', '-f=${db:Status-Status}', package], ok=(0, 1)).strip()
        if installed == 'installed':
            result['message'] = ('GTX 1660 Ti: NVIDIA packages are installed but driver telemetry is unavailable. '
                                 'Restart after updates, then check nvidia-smi and Local display. '
                                 'If still unavailable, review kernel module and Secure Boot status locally.')
            return result
    if any(gpu.get('driver') == 'nvidia' for gpu in nvidia):
        result['message'] = 'An unmanaged NVIDIA driver is loaded. Review its installation locally before adding packaged drivers.'
        return result

    def candidate(package):
        match = re.search(r'^\s*Candidate: (' + VERSION + r')\s*$',
                          run(['apt-cache', 'policy', package]), re.MULTILINE)
        return match.group(1) if match else None

    # New GPU-capable ISOs use NVIDIA's repository; older AirLink installations
    # have Debian contrib/non-free. Use only the already configured repositories.
    official = candidate('nvidia-open')
    packages = ['nvidia-open'] if official else ['nvidia-open-kernel-dkms', 'nvidia-driver', 'nvidia-smi']
    kernel = platform.release()
    if not re.fullmatch(r'[a-z0-9][a-z0-9+.-]*', kernel):
        result['message'] = 'Cannot identify the running kernel for NVIDIA driver installation.'
        return result
    packages += ['linux-headers-' + kernel, 'linux-headers-amd64',
                 'pciutils', 'mesa-utils', 'libgl1-mesa-dri']
    targets = []
    missing = []
    for package in packages:
        version = official if package == 'nvidia-open' else candidate(package)
        if version:
            targets.append(package + '=' + version)
        else:
            missing.append(package)
    if missing:
        result['message'] = ('GTX 1660 Ti driver could not be planned: no package candidate for '
                             + ', '.join(missing) + '. Check configured repositories and kernel headers locally. '
                             'Other PC updates can still be installed.')
        return result
    return {'targets': targets, 'kernel': kernel,
            'message': 'GTX 1660 Ti detected: missing NVIDIA graphics driver, kernel headers and graphics tools are included below. '
                       'Restart after installation, then verify NVIDIA driver status and Local display in PC settings → Overview. '
                       'Secure Boot may require local module-key enrollment. Monitoring and database services continue on the CPU.'}
