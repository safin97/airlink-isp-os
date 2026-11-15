# Online PC and driver updates

On an installed AirLink Linux PC, the owner opens **Diagnostics → PC & driver updates → Check online**. Review the package names, installed and proposed versions, then choose **Review and install** and confirm. The job continues in the background; status refreshes while it runs. Internet access is required for checks and downloads.

The updater uses the existing APT repositories, signature verification, package holds and driver branch pins. It updates installed system packages, kernel, GPU drivers and firmware, and offers the matching Intel/AMD CPU microcode package if available. CPU microcode is not a CPU hardware upgrade or a performance guarantee. It does not add repositories, switch NVIDIA branches, install arbitrary driver scripts, remove packages, downgrade packages, perform a distribution upgrade, or flash BIOS/UEFI firmware. Packages requiring removals or manual dependency changes require local maintenance.

Each reviewed plan expires after one hour and is tied to the installed package state and exact versions. Dependency changes require another review. Application updates, PC updates and restarts share a maintenance lock. AirLink itself remains updated through its signed **Software Updates** flow.

Before installation, the job checks package health and free disk space, downloads packages, and creates the existing AirLink database/configuration backup. This backup is not a complete OS image or automatic system rollback. Package configuration files are preserved. Monitoring or the dashboard can be interrupted by package service restarts. Keep the machine powered on; after successful installation, restart through **Software Updates → Restart system** to activate drivers and libraries.

Interrupted installation requires local recovery review, including `dpkg --audit` and the `airlink-pc-update-install.service` journal. Do not simply clear the recovery state. Check failures can be retried after resolving internet/repository issues. Checks use `airlink-pc-update-check.service`; both services use root-owned state under `/var/lib/airlink-system/pc-updates`.

Local Mac/browser preview shows this feature as unavailable and cannot update the host computer. Only the installed Linux appliance runs package operations. No package installation is started merely by opening Diagnostics or installing this feature.

APT behavior and repository verification follow the [Debian apt-get manual](https://manpages.debian.org/trixie/apt/apt-get.8.en.html) and [apt-secure manual](https://manpages.debian.org/trixie/apt/apt-secure.8.en.html).
