# GitHub update configuration verification

Repository: `https://github.com/safin97/airlink-isp-os`.

New ISO: `dist/github-enabled/AirLink-ISP-OS-amd64.iso`.
SHA-256: `e592acbd3c67c3c436c8c36947446c235cdec2ab00ff25116714e76ce035ba8b`.

- Local Git origin configured to the supplied repository. Source was subsequently uploaded to `main` on 1 November 2026.
- Generated an Ed25519 publisher key locally, private PEM mode 0600, directory mode 0700. Git ignores the key directory; Docker excludes it. Only the public key is included in deployment defaults and release artifacts.
- 70 Python tests passed, one Linux-only package identity test skipped on macOS. Eighteen tests cover the GitHub helpers, including safe source installation, key preservation, manifest compatibility, replay and tamper rejection.
- Isolated amd64 container with networking disabled: full provisioning and component verification passed. The correct source URL/public key were installed with root ownership. The updater reported configured. No publisher private PEM was present in the application tree.
- Separate updated ISO built successfully. It passed a fresh QEMU UEFI boot, rendered the graphical installer, and served HTTPS health with `status=ok`. No disk was attached to this follow-up boot test. The original ISO and visible user QEMU session were preserved.
- Initial repository, latest-release and signed-manifest checks returned HTTP 404. Repository access was subsequently resolved and the source push succeeded on 1 November 2026. No signed release upload or live signed update installation is claimed.

The original ISO's broader installation, networking and recovery evidence is in TEST-REPORT.md. This follow-up changes publisher provisioning, not the installation engine. Private-repository authentication, automatic publishing, and full OS updates/rollback are not implemented by this configuration.
