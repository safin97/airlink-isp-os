# Customer Telegram notifications

Owners can configure their customer bot directly under **My account → Telegram bot token**, without opening a customer record. This uses the same owner bot as the ISP card notification screen. It shows the bot username, enable switch, expiry timezone and connection errors; the saved token stays hidden. Configure the owner's SAS4 connection in ISP card first, then save the bot here and link customers from their ISP card details. The My account section is visible only to owners. All managers use this shared owner bot for customer notifications; managers cannot read or change its token.

Open **ISP card → customer details → Customer Telegram**. Save a dedicated bot created with **@BotFather**; use a different bot from manager device alerts and other applications. Only an owner can save the shared sender. Managers can see its public username and link status. There is one shared link per customer under the selected owner, so a customer linked by the owner also receives notifications after a manager activates their service. Both the manager and owner must be able to access the same SAS4 customer when the manager creates a link. Customer status, language changes and unlinking always require access through the requesting manager’s own SAS4 account. Tokens are encrypted on the server and never returned to the browser. Existing webhooks are refused rather than removed.

Choose the **SAS4 expiry timezone** (default **Asia/Baghdad**) to interpret SAS4 dates without an explicit timezone. Select the customer's message language: English, Kurdish Badini, or Arabic. Create a private link and give it only to that customer. Keep the invitation private. Possessing it starts enrollment, but notifications also require the customer's own Telegram phone to match their ISP card record. It expires after 24 hours, works once, and is stored only as a hash. Creating another link invalidates the previous invitation. The customer must open the link, tap **Start**, then tap **Share my phone number** in the private bot chat. AirLink accepts only a Telegram contact whose user ID matches the person sharing it. The shared phone must match the current ISP card phone and the phone recorded when the invitation was created. Typed numbers and someone else’s contact do not verify a link. The resulting link is bound to the SAS4 customer ID, username, verified phone fingerprint and Telegram chat ID. Opening another customer invitation before finishing phone sharing replaces the pending enrollment for that chat.

Save a valid phone number in ISP card before creating a link. International numbers with `+` or `00` are supported, as are Iraqi mobile numbers written as `07...` or `7...`; other local formats should be saved with a country code. Spaces, hyphens, parentheses and Arabic digits are normalized. Telegram phone verification stores a keyed fingerprint and verification time, not a second plaintext copy of the number. Each delivery rechecks the current ISP card phone against that fingerprint. A changed number blocks delivery and requires a new verification. This checks the last phone shared by the customer; it does not query Telegram for the phone currently attached to their account or determine whether arbitrary numbers have Telegram.

Linked customers receive confirmation after successful **card PIN**, **account balance**, **service extension**, **FIB**, and **FastPay** activation performed through AirLink. Bank payment messages require both verified production payment and confirmed SAS4 activation. Pending, declined, sandbox, uncertain or review-required transactions do not send activation confirmations. Events are deduplicated per transaction and customer link. Card PINs, passwords, payment credentials and phone numbers are excluded. Notifications show the customer username and the current expiry retrieved from SAS4 at delivery time. Changes performed outside AirLink do not generate activation messages.

The API's background worker checks linked customers approximately hourly, independently of open browsers. It queues one reminder when expiry is between 48 and 72 hours away, using the configured SAS4 timezone. It rechecks the expiry before sending; a renewed, changed or already expired service cancels an obsolete reminder. It does not backfill misleading three-day reminders after prolonged downtime. The shared customer link prevents separate expiry reminders from each manager. Only the selected owner bot is polled; manager bot credentials are never used as a fallback.

Customers can send **/stop** to unsubscribe from every customer link in that bot. Managers can select **Unlink customer** and create a fresh invitation when changing recipients. Old queued events cannot be delivered to a replacement recipient. Changing the bot or SAS4 account requires relinking. Disabling notifications discards pending events. Disabling the selected owner account or changing its SAS4 account stops collection and delivery. Each delivery verifies that the owner can still read the customer. Managers need ISP card edit permission to link, unlink, change language or activate service. A confirmed activation remains a customer event even if the activating manager later loses access.

**Refresh link and delivery status** shows the link state, latest delivery error and recent pending/sent/failed/cancelled events. Delivery retries up to five times with backoff. Telegram has no sendMessage idempotency key, so a timeout after acceptance can cause a duplicate on retry. Network failures never replay a recharge. Events are retained for 90 days. The worker serializes work through Redis and sends at most one customer message per five-second cycle; large queues and slow providers can delay notifications. Internet access to Telegram and SAS4 is required. No bot is configured and no customer is subscribed automatically.

Select **Send test to Telegram** on a linked customer's Telegram page to send an immediate test through the owner bot. Owners and managers with ISP card edit permission can test customers they can access in SAS4; the owner must also retain access. The test uses the customer's saved language and appears as **test** in delivery history. An existing customer-consented Telegram chat can receive a manual test even if it predates phone verification. This does not enable automatic notifications or mark the phone verified. Unlinked customers, disabled bots, and customers whose previously verified phone has changed cannot receive a test. The test uses the saved Telegram chat ID; it does not look up a Telegram account from the phone number. Repeated tests for the same customer are limited to one every 30 seconds. Tests are attempted once without automatic retries; an unconfirmed response may have reached Telegram, so check the customer chat before trying again. A successful response means Telegram accepted the message, not that the customer read it.

Migration `b38cf705196f` adds bot, link and event tables. Migration `c49da816207b` adds the shared owner sender selection. A single pre-existing active owner bot is preserved automatically. If several owner bots exist, an owner must save the intended sender rather than the system picking one arbitrarily. Existing manager-specific customer links must be recreated with the owner bot; their pending messages are cancelled. Migration `d50eb927318c` adds pending phone verification, a keyed phone fingerprint and verification timestamp. Older links are not marked verified automatically; customers must verify their phone before further notifications. Existing invitation links can still begin phone verification when the ISP card has a valid phone. Manager device alerts and SAS4 records are unchanged.

References: [Telegram deep links](https://core.telegram.org/bots/features#deep-linking), [Bot API](https://core.telegram.org/bots/api#getupdates), [Telegram phone sharing](https://core.telegram.org/bots/api#keyboardbutton).

## Owner Telegram account lookup

In **My account → Telegram account lookup**, an owner can connect their own
Telegram user account with an API ID and API hash from
<https://my.telegram.org> → API development tools. Enter the code delivered by
Telegram and, if enabled, the account's two-step verification password. This is
separate from the owner bot token. AirLink does not create Telegram accounts.

The owner sees an automatic, single phone check when opening **ISP card →
customer details → Customer Telegram**, plus **Check saved phone** to check again.
Only that owner's SAS4-accessible customer's saved phone is accepted. Managers
cannot access this login, session, or lookup. Each owner has a separate connection.

Lookup uses `contacts.resolvePhone`, without uploading contacts or reading chats.
It returns the accessible name, username and Telegram user ID. **Unknown** means
no accessible match; privacy settings can hide an existing account. Profiles are
not persisted. Lookup never changes a customer bot link, sends a message, or
substitutes for the customer's consent to start the bot and share their phone.
Owners can explicitly click **Send test from connected account** after a successful
lookup. The sender is the connected Telegram user account shown above the button,
not the owner bot. The test uses the language selected in Customer Telegram. It
contains only a generic AirLink test message, without customer credentials or
subscription details. Automatic activation and expiry messages still use the bot.

A five-minute encrypted token binds the displayed recipient to the current saved
phone, customer identity, owner and Telegram sender. A changed phone or sender
requires a fresh lookup. Tests are limited to one per recipient/sender every 30
seconds. Tokens are single-use, with a fixed Telegram random ID for duplicate
protection. There are no automatic message retries; ambiguous failures tell the
owner to check the chat. Telegram privacy, blocking, paid-message and account
restrictions can prevent delivery. AirLink does not authorize Telegram Stars
payments. A successful result means Telegram accepted the message, not that it
was read. Existing owner-bot tests remain separate.

Sessions, API hashes and pending phone/code-hash values are encrypted with the
appliance encryption key. Login codes and two-step passwords are never stored.
Pending login attempts expire after ten minutes. Account operations are serialized
across API processes; lookups are limited to one per three seconds per Telegram
identity. Telegram flood-wait cooldowns are honored and errors are redacted.
Disconnect requests remote logout before deleting the local session. If offline,
retry or revoke **AirLink ISP OS** in Telegram **Settings → Devices**. Database
backups contain the encrypted session, so protect the backup and encryption key.

Deployment requires the new Alembic migration and the pinned Telethon dependencies
in `backend/requirements.lock`; rebuild the runtime image before packaging an
update. No real account is connected by the automated tests.

References: [Telegram phone lookup](https://core.telegram.org/method/contacts.resolvePhone),
[Telethon login](https://docs.telethon.dev/en/stable/basic/signing-in.html),
[session security](https://docs.telethon.dev/en/stable/concepts/sessions.html).


## Automatic phone-based recharge receipts

In **My account → Telegram account lookup**, enable **Send after every successful
recharge** and save. The selected owner's connected Telegram user account becomes
the shared sender for owner and manager recharges. Its SAS4 account must also be
able to access the same customer. The receipt is addressed by resolving the saved
customer phone through Telegram. Privacy-hidden numbers are marked skipped;
blocking or Telegram account restrictions may prevent delivery.

Card PIN, account balance, extension, FIB and FastPay all enqueue only after a
confirmed activation. FIB/FastPay additionally require verified production payment;
pending, declined, sandbox and unconfirmed activations never generate receipts.
A transaction creates one receipt. This account route replaces the bot's recharge
message while enabled, avoiding two notifications for one activation. Existing
bot expiry reminders and manual tests remain separate.

The receipt contains method, account, transaction reference, confirmation time,
masked card suffix and available service plan, extension, updated expiry, service
price and SAS4 manager recharge cost/currency. The manager cost is the validated
activation cost for balance, FIB and FastPay, the extension quote cost for extensions,
and the activation data's manager cost for card PIN when SAS4 provides it.
It never includes the full card PIN, customer password or manager balance. Details are collected after activation
on a best-effort basis. Missing SAS4 details are omitted. The queued receipt is
encrypted; later profile changes do not rewrite the original receipt. The language selected in **Telegram account lookup** is saved immediately and
applies to all ISP card customers, including account tests, bot notifications, and
queued recharge receipts that have not been sent yet. Older per-customer languages
do not override it. Customer Telegram shows the shared selection as read-only.
Changing language does not enable automatic sending or change the selected sender.
Without a shared setting, legacy per-customer language behavior is retained.

The worker checks current owner/manager permissions, SAS4 connections, customer
identity and the original phone fingerprint before sending. It cancels delivery
when these change. Settings changes and Telegram sends are serialized. Successful
receipt delivery never triggers another activation. Preparation failures can retry;
a timeout/crash after starting a send stays unconfirmed and is not automatically
resent. Telegram random IDs provide additional duplicate protection. No Telegram
Stars payment is authorized. A sent status means accepted by Telegram, not read.

**Customer Telegram → Recharge notifications from owner account** shows recent
status and errors; use **Refresh link and delivery status** to update it. Nonpending
receipt history is retained for 90 days. Migration `f72adb49530e` adds the settings
and encrypted receipt queue. Existing installations start with this account route
disabled until an owner enables it; no historical recharges are sent.

## Editing account notification messages

Open **My account → Telegram account lookup → Edit notification message**. The
editor follows the selected customer language. Choose card PIN, balance, extension,
FIB, FastPay, or phone test; edit the plain text and choose **Save message**. Each
language and message type has its own template. Save before changing language or
type. **Restore default** resets only that language/type. Edits apply to future
sends, including queued receipts that have not been sent. Existing sent messages
are not changed. The separate bot message system is unchanged.

**Preview message** uses sample customer data and never contacts Telegram. Allowed
placeholders are `{username}`, `{method}`, `{profile}`, `{expiration}`,
`{reference}`, `{card}`, `{extension}`, `{recharge_cost}`, `{service_price}`, `{currency}`,
`{date}` and `{details}`. `{details}` includes all available receipt details with
localized labels; individual missing values become empty. Amount placeholders
contain the amount; use `{currency}` separately when needed. `{recharge_cost}`
replaces the old `{amount}` placeholder; older saved templates are automatically
shown with the new name. It shows the SAS4 manager recharge cost, while
`{service_price}` is the customer service price. Previously queued receipts without
a manager cost leave it blank; customer payment amounts are not substituted for
manager costs. Zero costs are displayed. `{card}` is masked.
Phone tests have account, plan, expiry and a `TEST` reference when available.

Only owners can edit or preview these shared templates. Saving a template does not
enable sending, switch the sender or change the customer language. Unsupported
placeholders, attribute/index access and formatting instructions are rejected.
Templates are limited to 1,500 characters, with a conservative 4,000 UTF-16-unit
expanded length bound. Telegram messages use plain text, without HTML/Markdown
parsing. Migration `a83bec50641f` adds the template table; existing messages keep
their built-in wording until an owner saves a custom template.

## Expiry message types and automatic alerts

The message editor also includes **Expires in 3 days** (`expiry_3days`) and
**Service expired** (`expired`), each with English, Kurdish and Arabic defaults.
They use the same editable placeholders; expiry details use service-expiry and
notification-time labels instead of recharge labels.

**Automatic expiry alerts** is a separate, immediately saved switch and starts
disabled. Enable it to scan the selected owner's SAS4-visible customers in the
background. One page of 25 customers is checked per minute; a completed pass is
followed by an hourly pause. Each expiry date generates at most one warning while
48–72 hours remain and one expired notice during the first 24 hours after expiry.
Older expired services and disabled users are skipped. The owner account must be
connected and still have SAS4 access. This switch is independent of the recharge
notification enable switch.

Every send rechecks the actual expiry, account identity, saved phone and current
alert window. A renewal, changed identity or stale reminder cancels delivery.
Events share the existing encrypted queue, privacy-aware phone lookup, cooldowns
and no-automatic-resend behavior after an ambiguous send. Turning on account
expiry alerts suppresses the old bot three-day reminder, including queued bot
reminders, to avoid duplicate delivery. Turning alerts off does not resend old
events. Status is visible in Customer Telegram and **Refresh expiry check status**.
Migration `b94cfd617520` adds the persistent scan schedule. Installing the feature
or previewing/editing these templates does not enable automatic expiry messages.
