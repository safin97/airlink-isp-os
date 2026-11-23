# TTLock in AirLink

AirLink's TTLock section is restricted to owners and their connected TTLock administrator account. Managers and public client accounts cannot use the lock APIs. The website and Android/iPhone apps share the existing AirLink backend and account login.

## Connect your account

1. Obtain an approved TTLock Open Platform application's Client ID and Client Secret.
2. In AirLink, open **TTLock → One-time integration setup**. Choose the server matching your TTLock application/account: Europe or China. Save the application credentials once.
3. Sign in using your **TTLock app** username and password, not your developer-account password. Telephone usernames require the country code, for example `+964…`.
4. Existing administrator-owned locks appear. Shared eKeys are not included in this list. Customized owner navigation must allow the TTLock section.

No working TTLock account or developer application is bundled. Application credentials are required even when the normal login screen shows only username/password.

## Website and mobile capabilities

| Operation | Website | Android / iPhone |
| --- | --- | --- |
| Account connection, devices, names and last reported battery | Yes | Yes |
| List cards, custom passcodes and fingerprints; rename them | Yes | Yes |
| Add/remove cards, custom passcodes and fingerprints | Through an approving phone bridge | Nearby Bluetooth, then cloud synchronization |
| Change a credential's validity period | Through an approving phone bridge | Nearby Bluetooth; recurring/special credentials remain in TTLock |
| Pair a new lock | Guided app instructions | Scan, initialize over Bluetooth, register in cloud |
| Remove a lock | Through an approving phone bridge | Confirm physical reset over Bluetooth, then cloud deletion |
| Lock/unlock and check status | Phone bridge, or supported gateway/Wi-Fi | Nearby Bluetooth |
| Read battery, synchronize clock and read access records | Through a phone bridge | Nearby Bluetooth; records currently displayed as device JSON |

Your Bluetooth-only locks require the AirLink mobile app near the device for physical changes. The website can send work through that app using **Use phone Bluetooth**; it does not implement direct Web Bluetooth lock commands. The phone also needs internet access to authenticate, obtain current owner credentials and synchronize results. This is not an offline-key wallet.

This implementation is not full TTLock-app feature parity. Firmware updates, eKey sharing/transfer, recurring schedule editing, gateway provisioning, face/palm credentials, wireless remotes/keypads and advanced lock settings remain in the official TTLock app. Hardware capabilities vary; a successful build does not establish compatibility with every lock model.

## Use the mobile app

1. Install the Android test APK, or sign and install the iOS build using your Apple development team.
2. Enter your AirLink server's **HTTPS origin**, for example `https://airlink.example.com`. The certificate must be trusted by the phone. Update the server with this backend and migrations first.
3. Sign in with your existing AirLink owner account, then connect TTLock as above.
4. Allow Bluetooth / Nearby devices permissions. Android also requests location permission for discovery.
5. Open a lock's **Cards & device** screen and tap **Connect via Bluetooth**. Wake the lock and keep the phone nearby. A successful battery read displays the verification time and battery; this checks communication without unlocking the door. Each later action reconnects as needed. Then choose Cards, Passcodes or Fingerprints. For card enrollment, present the card to the lock reader when prompted. For fingerprints, touch the lock's sensor as prompted; AirLink receives a numeric credential reference, not a fingerprint image.
6. For a new uninitialized lock, use **Add Bluetooth device**. Stay near the lock until cloud registration finishes. Already initialized devices must belong to your connected TTLock account.

Mobile builds use `lib/main_mobile.dart`. The website continues to use `lib/main.dart`. Run from `frontend`:

```sh
flutter pub get
flutter build apk --debug -t lib/main_mobile.dart
flutter build ios --debug --no-codesign -t lib/main_mobile.dart
flutter build web --release --no-web-resources-cdn
```

Android debug APK: `frontend/build/app/outputs/flutter-apk/app-debug.apk`. Debug signing is for testing, not store distribution. iOS requires an Apple signing team/provisioning before installation or TestFlight; the unsigned `.app` is a build verification artifact. Deployment targets are Android API 24+ and iOS 15+.

On a macOS Desktop folder synchronized by a file provider, Flutter framework signing can fail because Finder metadata is attached to generated bundles. Build from a clean checkout outside that synchronized folder if this occurs. The SDK's small Android Gradle compatibility patch is documented in `frontend/vendor/ttlock_flutter/AIRLINK_PATCHES.md`; upstream license is retained.

## Recovery and privacy

### Chrome on a computer, Android or iPhone

1. Install the updated AirLink Android app, or sign/install the updated iPhone app. Update the backend through migration `f42bc1583d69`. Both browser and app must reach the same updated HTTPS server.
2. Sign in to the same AirLink **owner account** and connect the same TTLock account on both devices.
3. In the phone app open **TTLock → Share Bluetooth with website**, give the phone a recognizable name and press **Start Bluetooth sharing**. Keep the app open near the locks.
4. In Chrome open **TTLock → [your lock] → Use phone Bluetooth**, select that phone, and choose an action. **Check phone Bluetooth** requests a battery read without unlocking the door.
5. Review the lock/action on the phone and press **Approve and run** (or **Decline**). Enrollment prompts appear on the phone; present cards/fingers at the lock when prompted. The browser shows the phone's actual result.

Sharing uses the phone app's SDK, so Chrome on iPhone is supported as a control page despite lacking direct Web Bluetooth. There is no background gateway service: keep the native app in the foreground. If Chrome and AirLink are on the same phone, switch back promptly to approve; using another nearby phone is more convenient. A phone stays listed for up to two minutes after its last heartbeat, and a queued request expires after two minutes. Leaving sharing stops it; an abruptly closed app expires without requiring manual cleanup.

Each phone accepts one pending request at a time. The backend atomically claims a request once, binds sharing to the owner and TTLock account, and stores credential payloads/results encrypted. Polling exposes the requested action and lock name, not the credential value. A claim secret is required to record completion. Cancelling is allowed only before execution starts. Running requests without a result become **unknown**, never automatically queued again. The phone saves result delivery in secure storage and offers **Retry sending result only** after a network failure. It does not repeat Bluetooth. If storage fails, keep the app open until delivery succeeds. New-lock discovery/pairing remains directly in the phone app.

### Physical changes and cloud synchronization

Physical credential changes happen through the SDK first. Only a successful result is uploaded to TTLock Cloud using its Bluetooth-completed method. The server journals operations before the device action. Successful SDK results are saved in the phone's secure storage before upload; **Recover sync** retries cloud synchronization without repeating Bluetooth. Ambiguous cloud responses are reconciled against current provider records before registration is retried. An SDK timeout is an unknown physical result: inspect the lock before starting another action.

Keep the original phone and original TTLock account until pending work is synchronized. If secure storage fails after a device change, keep the app open and recover immediately; the in-memory fallback does not survive app termination. An interrupted operation without a received SDK result cannot be automatically assumed successful. Do not reset or re-enroll solely because cloud synchronization is pending.

Client Secret, provider tokens and operation payload/results are encrypted on the backend using AirLink's existing encryption key. The TTLock password is used for its required login exchange and is not persisted. Ordinary lock lists omit `lockData`. The explicit owner-authorized Bluetooth endpoint returns lock credentials to the authenticated app when needed. Credential-list endpoints return real access codes only to the lock owner and set `Cache-Control: no-store`; passcodes are masked by default in the UI. Native AirLink refresh cookies use secure storage, are restricted to the configured HTTPS origin/auth path and are cleared on logout.

Disconnect removes the AirLink connection, not devices from TTLock. Saved application setup remains available for the next login. Changing the connected TTLock account prevents pending operations from being synchronized into the wrong account. Naming, removal and command confirmations identify the selected lock. No automatic physical-command retry is performed.

## Deployment and verification

### Smart-lock dashboard

The TTLock dashboard and device pages use a scoped light/dark theme, responsive summary cards, grid/list views, Lucide icons and loading placeholders. Other AirLink modules and the sidebar keep their existing appearance. Device names and IDs come from the existing account; opening a card does not change the device.

Search, connection filters, verified online/failed-check counts and low-battery counts cover the current API page. Total Smart Locks uses the provider's total. Gateway linkage alone never establishes that a lock is online. Lock state starts unknown, is populated only by a successful state query and expires after two minutes. Commands do not infer a new physical state, and sensitive commands retain confirmation and duplicate-request protection.

Device tabs expose the existing cards, timed/permanent passcodes, fingerprints, validity, naming and synchronization workflows. eKeys, recurring/one-time passcode generation and separate user assignment remain visibly disabled because this integration does not expose those APIs. Gateway Management shows reported linkage for real locks; gateway IDs, online status and connection times remain unavailable, and gateway creation/edit/removal is disabled. No new backend endpoints or migrations are required by this UI redesign.

Records are downloaded through the existing native Bluetooth or phone-bridge operation. The timeline searches and paginates the returned records. Unknown method codes remain numeric and success/failure is shown only when explicitly supplied; missing users and outcomes are labeled as not reported. Cloud access-history retrieval is not available in this integration.

The automated UI checks cover phone, tablet and desktop sizes in both themes, disabled unsupported actions, navigation and duplicate command confirmation. Physical lock/unlock, Bluetooth enrollment/deletion, phone-bridge approvals, real record formats and gateway connectivity still require testing with the owner's hardware. Browser widget rendering and compiled builds do not replace those hardware checks.

Files changed for the dashboard redesign (relative to the project root):

- `frontend/lib/ttlock.dart` — existing account screen and dashboard integration.
- `frontend/lib/ttlock_dashboard.dart` — summary metrics, search/filter, grid/list and lock cards.
- `frontend/lib/ttlock_style.dart` — scoped theme, shared panels, badges, battery and lock illustration.
- `frontend/lib/ttlock_device_page.dart` — device tabs and existing access-management workflows.
- `frontend/lib/ttlock_gateway_page.dart` — gateway-link visibility and capability explanations.
- `frontend/lib/ttlock_records.dart` — actual device-record parsing, filters and timeline.
- `frontend/pubspec.yaml`, `frontend/pubspec.lock` — Lucide icon dependency.
- `frontend/test/ttlock_redesign_test.dart` — responsive themes, all device tabs, gateway layout and records.
- `frontend/test/ttlock_test.dart`, `frontend/test/ttlock_devices_test.dart`, `frontend/test/ttlock_cards_ui_test.dart` — updated navigation and command-confirmation regression checks.
- `docs/TTLOCK.md` — scope, capability limits, file list and verification guidance.

Redesign validation: Flutter analysis reported no issues; all 291 Flutter tests passed. Release web, debug Android APK and unsigned debug iOS builds succeeded. The final web build used `--no-wasm-dry-run` after an optional dry run stalled; an earlier WebAssembly dry run passed. Rendered previews were inspected in light/dark mode using the account's read-only lock list. Direct Chrome automation was unavailable, so live browser interaction and physical hardware behavior are not claimed as verified. The changes are built locally, not deployed to the public server.

Apply the normal database upgrade through `f42bc1583d69` and restart the backend. Earlier TTLock migrations are `c19ef8250a36`, `d20fa9361b47`, and `e31ab0472c58`. The migrations add the application setup, encrypted mobile-operation journal, foreground phone sessions and encrypted relay jobs. Local `tests/preview.py --live` creates missing tables on startup.

Automated tests use mocked Cloud and Bluetooth responses. They cover ownership, credential validation, encrypted storage, native sessions, Bluetooth-before-cloud ordering, recovery, duplicate suppression and narrow-screen UI confirmations. Real TTLock login, phone permissions, enrollment and lock operation require testing with an approved application, a physical phone and your lock. No physical device was modified during implementation.

Official references:

- [Flutter SDK](https://euopen.ttlock.com/document-pages/en/userGuide/flutter)
- [Application setup](https://euopen.ttlock.com/document-pages/en/userGuide/getStarted)
- [Add IC card](https://euopen.ttlock.com/document-pages/en/cloud/card/add)
- [Custom passcodes](https://euopen.ttlock.com/document-pages/en/cloud/passcode/add)
- [Fingerprints](https://euopen.ttlock.com/document-pages/en/cloud/fingerprint/add)
- [Lock initialization](https://euopen.ttlock.com/document-pages/en/cloud/lock/initialize)
- [Lock removal](https://euopen.ttlock.com/document-pages/en/cloud/lock/delete)
