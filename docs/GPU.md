# GPU detection and local graphics acceleration

Release 0.1.6-dev is an application-only update: it includes detection/status reporting but does not ship a new ISO or install drivers. The GPU-capable ISO recipe below is separate.

The GPU-capable ISO build recipe includes NVIDIA's Debian 13 open kernel driver from the 610 branch, its user-space graphics libraries and `nvidia-smi`. Drivers are built for the ISO kernel before packaging, so a supported RTX card can bind through normal Linux PCI/udev detection without an Internet download at boot. Mesa remains installed for other graphics hardware. AirLink does not force an Xorg primary GPU or change laptop GPU routing.

Dashboard → PC performance displays GPU utilization, VRAM use, temperature and driver status for each detected GPU. Missing readings are marked unavailable. PC settings → Overview shows every detected PCI display/3D controller. For an active NVIDIA driver, it also shows the model, driver version, VRAM use, utilization and temperature reported by `nvidia-smi`. Missing drivers and unavailable metrics are shown honestly; zero utilization is a valid idle reading. Detection is read-only and never downloads drivers, reboots, changes power limits or overclocks hardware.

GPU models are detected automatically from PCI hardware IDs. Names come from `lspci`, with an offline `pci.ids` database fallback if the tool is unavailable or returns only numeric labels. The database is cached by its revision and the detected GPU IDs, and new images include PCI tools and the name database in the base system. A working NVIDIA driver's model name takes priority. The GTX 1660 Ti laptop has a built-in name fallback when neither naming source is available; other unknown IDs remain visible without guessing a model. Overview, PC performance and Diagnostics use the same resolved GPU names. Model identification does not imply driver readiness or GPU utilization.

The open NVIDIA module targets Turing and newer GPUs, including RTX generations supported by the bundled driver. Physical RTX acceleration is not verified by an emulated QEMU test. A virtual machine only sees the GPU assigned to it; a virtual display adapter does not expose the host RTX card. Secure Boot with this custom ISO and its locally built modules is not qualified; administrator-managed signing/enrollment may be required.

The GPU accelerates compatible graphics/compute applications. The current AirLink monitoring worker uses CPU/network/database operations and does not run CUDA kernels. The web dashboard uses the GPU of the computer running its browser when browser acceleration is available, which may be a different computer from the AirLink server.

## Local display

The installed console starts through `os/console/graphics.py`. It prefers NVIDIA OpenGL using PRIME render offload, then tries the default hardware renderer (including Intel/AMD), then starts with standard CPU rendering. Each hardware candidate must pass a bounded `glxinfo` check and an isolated Qt OpenGL frame test. Software OpenGL renderers such as llvmpipe are not reported as hardware acceleration. Missing tools, missing drivers, failed contexts and probe timeouts leave the panel usable with standard rendering. If the accelerated panel crashes, the launcher retries once with CPU rendering; intentional service stops do not restart it.

The panel uses Qt 6.8's `QT_WIDGETS_RHI=1` and `QT_WIDGETS_RHI_BACKEND=opengl` for OpenGL compositing. Normal widget painting and monitoring remain CPU work. No fixed GPU utilization is requested: idle utilization may be zero. No power limit, clock setting, CUDA workload or global GPU routing is changed. Settings are confined to the local panel's child processes. **PC settings → Overview → Local display** reports the selected renderer, separately from driver/telemetry status.

This works on installations with compatible NVIDIA drivers and the existing Mesa/Qt graphics tools. Application updates do not provision missing kernel drivers; older installations without these prerequisites use standard rendering. The ISO recipe already includes those prerequisites. The browser dashboard remains governed by the browser computer's graphics settings.

Validation covers renderer selection, probe failures/timeouts, crash fallback, service shutdown, and Qt panel interactions through OpenGL and standard rendering in an isolated Linux X11 environment. That environment uses Mesa software OpenGL to exercise the rendering code; physical NVIDIA acceleration still requires a check on the target PC. The probe checks actual displayed pixels and Qt's OpenGL composition diagnostics, so unsupported Qt versions fail back to standard rendering.

This is an ISO/base-system addition. The existing application-only GitHub updater does not install NVIDIA kernel modules or system drivers on older installations.

## Install a missing GTX 1660 Ti laptop driver

The owner can now use **Diagnostics → PC & driver updates → Check online** on an installed amd64 AirLink PC with NVIDIA PCI device `10de:2191`. The check includes a missing driver in the existing package review. Choose **Review and install**, wait for completion, then use **Software Updates → Restart system**. Merely opening Diagnostics or installing an AirLink application update does not install drivers or restart the PC.

The plan uses `nvidia-open` if available in the configured NVIDIA repository, otherwise Debian's `nvidia-open-kernel-dkms`, `nvidia-driver` and `nvidia-smi`. It includes running-kernel headers, the amd64 header metapackage, PCI tools and Mesa graphics tools. Missing candidates are reported without offering a partial driver installation. Existing NVIDIA package families and working drivers are preserved; an installed but nonfunctional driver requires local diagnosis rather than automatic replacement. Mixed NVIDIA models require a compatibility review.

Installation verifies that an NVIDIA module exists for the reviewed running kernel. This is a build check, not proof that the hardware driver is running. After reboot, confirm `nvidia-smi` works, **PC settings → Overview** reports NVIDIA driver readiness, and **Local display** reports NVIDIA OpenGL compositing. Secure Boot can require local module-key enrollment; the updater does not disable it or remove DKMS signing keys. The laptop's physical driver and display must be verified on that laptop.

PCI `2191` is also recognized by name when the PCI name database is unavailable. A known model name does not imply that its driver is loaded. The monitoring worker and database still use CPU processing; the driver enables supported graphics workloads, not full-system GPU execution.

Package references: [NVIDIA Debian driver installation](https://docs.nvidia.com/datacenter/tesla/driver-installation-guide/debian.html), [Debian open kernel module](https://packages.debian.org/trixie/nvidia-open-kernel-dkms), [Debian graphics driver](https://packages.debian.org/trixie/nvidia-driver).

For a read-only diagnostic from the local recovery shell, run `python3 /opt/airlink/os/console/gpu.py`. It prints detected hardware and available telemetry as JSON.

Sources: [NVIDIA Debian installation](https://docs.nvidia.com/datacenter/tesla/driver-installation-guide/debian.html), [NVIDIA kernel modules](https://docs.nvidia.com/datacenter/tesla/driver-installation-guide/610/kernel-modules.html).

Rendering references: [NVIDIA PRIME render offload](https://download.nvidia.com/XFree86/Linux-x86_64/550.135/README/primerenderoffload.html), [Qt 6.8 OpenGL backing-store support](https://github.com/qt/qtbase/blob/6.8/src/gui/painting/qbackingstorerhisupport.cpp).
