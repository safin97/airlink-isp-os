# Run AirLink locally in VS Code

The local application is available at **http://127.0.0.1:18080/**. It uses the saved local database and accounts. The Mac's internet connection is used for outgoing SAS4 and device requests; no public hosting or port forwarding is needed.

## Live mode

In the repository's VS Code terminal, run:

```sh
./scripts/live.sh
```

Equivalent: `make live`. This uses the existing web build, enables real SAS4 calls and polls enabled inventory devices in the background using their saved ICMP, SNMP and device API settings. Online-user snapshots and customer telemetry refresh even when no page is open. The terminal prints `AirLink local mode: LIVE` at startup. Keep the process running while using the app; Ctrl+C stops it.

Use **SAS4 connection** to save your real SAS4 login for your local account. Existing real connections are preserved. Live mode removes only the exact synthetic SAS4 connection fixtures originally created by the demo launcher; it preserves their accounts. It never replaces live readings with sample online-user data. Saved private device IPs still need a working LAN or VPN route from the Mac; internet access alone cannot reach an isolated tower subnet.

The server binds only to `127.0.0.1`. It is a local development runtime using SQLite and an in-process Redis substitute, not the installed Linux appliance. Live mode checks new FIB payments that reserve a Card System PIN every 20 seconds, even after the checkout window closes. For new checkouts, verified production payments automatically recharge the customer with the reserved PIN; sandbox payments release the reservation without revealing or using it. The local launcher processes saved-card payments only; it does not automatically activate manager-balance payments. Older manual PIN orders retain their original behavior. Live mode evaluates device alerts and dispatches Telegram notifications when the owner has enabled them. Appliance networking and OS updates/restarts require the installed Linux system.

**ISP Card → Reports → System Cards** reads live SAS4 Radius card series using the signed-in account's saved SAS4 connection. It shows series, date added, card type, value, quantity, used count, owner, profile, addon, expiration and suspension status. Search and pagination are supported; the SAS4 manager filter selects the card owner. The selected page refreshes every 15 seconds. This read-only report does not import PINs into local Card System inventory or modify SAS4 cards.

**ISP Card → Card System → SAS4 Radius** reads and manages live SAS4 card series using the signed-in owner's saved SAS4 connection. Search, owner filtering, pagination and a 15-second series refresh are supported. Click a series to view its cards; PINs and prepaid passwords are hidden until **Show PINs** is selected. Available actions follow the SAS4 account's permissions: suspend/release, change owner, change expiry, and delete. Every change requires confirmation, runs directly against SAS4, and is audited locally. Failed or timed-out changes are not retried automatically; refresh before retrying. No remote mutation is performed by opening the page.

**Saved FIB PINs** retains the existing encrypted local inventory and profile/price settings for older orders. New dashboard FIB checkouts now select an unused PIN directly from SAS4 Radius; they no longer require manually copying a PIN into local inventory.

Open a customer's **Recharge card → FIB Bank**. AirLink searches SAS4 refill-card series for the customer's current profile, excludes suspended/expired series and used or locally held PINs, and charges the **SAS4 card value in IQD**. The SAS4 server currency must be IQD. The quote never exposes the PIN. **Continue to FIB payment** rechecks the customer profile/expiry, selected card, card value and availability, then commits an encrypted PIN hold before creating the bank payment. Changed quotes must be refreshed; no payment is created when a matching unused card is unavailable.

A database uniqueness constraint prevents multiple AirLink payments from holding the same SAS4 card, even across local accounts. This is an AirLink hold, not a remote SAS4 inventory lock: use outside AirLink can still consume or change the card. After timely production payment is verified, AirLink rechecks the held PIN, series eligibility, card value and customer profile/expiry before submitting the PIN once to SAS4. If the PIN changed or was used elsewhere, payment remains locked for owner review; AirLink does not silently choose another card or replay activation. New holds use migration `a97cd6038e14`; local startup creates this new table without altering existing inventory or orders.

The checkout displays **Pay with FIB** (and Business/Corporate buttons when returned by FIB), a QR code, and a readable payment code. The bank-issued HTTPS app link opens in the current browser context so Android and iOS can hand it to the FIB app. Customers on another device can scan the QR instead. **Copy customer payment link** copies the FIB Personal payment URL for the customer to open on their phone; it does not share AirLink credentials or the recharge PIN. Bank app links are accepted only over HTTPS on the expected FIB app hosts for the selected environment, including the current sandbox hosts `p-stage.fib.iq`, `b-stage.fib.iq`, and `c-stage.fib.iq`. If FIB omits a valid app link, the QR and readable code remain available. Opening a link never marks an order paid: server verification still checks the payment ID, amount, and currency.

For new FIB checkouts, payment verification automatically starts a SAS4 **card** recharge using only the held SAS4 Radius PIN. The server verifies the paid payment ID, amount, currency, and payment window before activation, then rechecks the customer's profile and expiry in SAS4 before submitting the PIN. A successful recharge consumes the PIN in SAS4, keeps the local hold as a record of its use, and never exposes the PIN to the checkout. Unconfirmed or interrupted activation stays reserved for owner review and is never retried automatically. This work continues even if the browser is closed or the customer opens FIB on their phone.

Older orders created for manual PIN issuance keep **Show recharge PIN → Use PIN to recharge**; they are not retroactively activated. New checkouts require an unused SAS4 Radius refill card assigned to the customer profile. If no available readable PIN matches, no bank payment is created. The new profile/price columns are added by migration `f86bc5928d03`; the local preview adds them on startup without changing existing PINs.

FIB payments have a five-minute window (`expiresIn: PT5M`). Checkout displays a countdown and hides the Pay buttons, payment code, and QR when that window ends, including after reopening the window. FIB expires the request independently of the browser. AirLink also checks the bank and requests cancellation if it is still unpaid after the deadline. Only a bank-confirmed decline/expiry releases the reserved card and marks the order `expired`; that order can never reveal or use the PIN. If confirmation is unavailable, the PIN stays reserved and locked while checking continues. A payment received within the window can still be verified afterwards. Late payments or missing payment timestamps after the deadline require owner review and do not unlock a PIN. **Start new payment** refreshes the card and price after confirmed expiry, and requires another explicit payment action.

Pending payments reserve their card. A bank-confirmed decline or completed sandbox test releases it. FIB authentication failures, connection failures before submission, and explicit creation rejections are marked `creation_failed`, show the cause, and release the reserved card. **Review price and retry** refreshes the quote and transaction ID; creating the next payment still requires an explicit click. Timeouts after submission, invalid success responses, and server errors remain `creation_unknown` with the card reserved.

Use **My account → Payment setup → Test saved FIB connection** (or **Check FIB connection** on a failed checkout) to check authentication and protected payment API access without creating a payment. Sandbox uses `https://fib-stage.fib.iq`; the legacy dotted staging host can issue a token that the payment API rejects as `invalid_token`. HTTP 401 `invalid_client` means the bank rejects the configured client credentials; save the merchant client ID and secret issued by FIB for the selected environment. Saving credentials alone does not verify them.

Older `creation_unknown` attempts without a bank payment ID can be released only by the owner using **Review unconfirmed payment**, after explicitly confirming in FIB that no payment was created or paid. The review is audited and does not create another charge. A successful connection test or a current credential failure does not establish the outcome of an earlier attempt. Known bank payments cannot be released through this review action. FIB merchant credentials and network access are required; tests with mocked providers do not validate a live merchant account.

## Client recharge

The separate customer page is **http://127.0.0.1:18080/client**. Owners configure it in **My account → Client portal**. It supports PIN recharge, FIB payments and SAS4 customer login, plus IP-based automatic login for explicitly configured subscriber networks. See [client portal setup and networking](CLIENT-PORTAL.md).

## Build changes or use demo mode

After editing Flutter code, build and start live mode with:

```sh
FLUTTER_BIN='/absolute/path/to/flutter/bin/flutter' ./scripts/preview.sh --live
```

For demo SAS4 data without background device polling:

```sh
./scripts/preview.sh --skip-build
```

Omit `--skip-build` to rebuild the dashboard first. Stop the existing local process before starting another on the same port. Use `./scripts/live.sh --port 18081` for another port, but do not run multiple live monitors against the same local database.

## Local data and login

Owners can use **Settings → Backups → Download a backup** to save an encrypted copy of the local SQLite database and its credential recovery key, or **Restore from PC file** to browse, upload and verify a previously saved backup. See [download and recovery instructions](DOWNLOAD-BACKUPS.md). Google Drive settings and scheduling have been removed.

[MEGA cloud backups](MEGA-BACKUPS.md) can upload this local archive on demand or weekly while the Mac is awake and the live launcher is running. Set up your own MEGA account in **Settings → Backups**. MEGA settings are kept in the private, ignored `.local/mega-backups/` directory.

Owners can use **Restore from MEGA** to select, download and verify a backup. Type `RESTORE` to confirm, then stop the server and run `./scripts/live.sh` again. Recovery saves a safety copy before replacing the database and its encryption key. Sign in with an account from the restored backup. An exclusive launcher lock prevents running two local servers against the same database during recovery.

The current launcher stores data in `/tmp/airlink-browser-qa.sqlite`. It reuses existing accounts, passwords, inventory and credential profiles on restart. If there is no existing database, it initializes the development owner defined in `tests/preview.py`. A restart refreshes local session signing keys; the browser can refresh a saved session or you can sign in again with your existing local account.

This `/tmp` database is temporary development storage and should be backed up before cleanup or reinstalling the Mac. Before the first switch to live mode, the existing database was copied to `/tmp/airlink-browser-qa-before-live-20261110T084432Z.sqlite`. It includes the previous readings and demo connection state. Keep database copies private because they include account data and encrypted device credentials.

The live launcher does not publish to GitHub or change your separate installed AirLink server. Internet, routing and authentication failures are shown as actual errors or unavailable readings; check the local terminal log and the relevant saved connection settings.
