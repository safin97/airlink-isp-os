# WhatsApp customer notifications

AirLink supports the official WhatsApp Business Cloud API for ISP card customers. These are WhatsApp messages, not carrier SMS. The integration operates independently of Telegram. It sends from one owner-selected WhatsApp business phone number.

## Setup

1. In Meta, configure a WhatsApp Business Account and registered Cloud API phone number. Create a system user token with `whatsapp_business_messaging` and `whatsapp_business_management` access to those assets. Set up Meta billing if required for the account. Never put the token in a URL or share it with customers.
2. Create the three utility templates below in WhatsApp Manager and wait for approval. AirLink accepts a body with numbered positional variables and an optional static footer; headers, buttons, media and named variables are not supported by this integration. Do not include card PINs, passwords or payment credentials.
3. In **My account → WhatsApp notifications**, enter the phone number ID, WhatsApp Business Account ID, system user token, Graph API version, template names, exact approved language code and SAS4 expiry timezone. IDs are Meta IDs, not phone numbers. Save with all notification switches off.
4. Choose **Check connection and templates**. This reads the business phone and template approvals; it does not send a message. The token is encrypted at rest and is never returned to the browser. Leave the token field blank on later saves to preserve it. Changing credentials, IDs, language or templates requires turning notifications off and checking again.
5. Enable the desired triggers and save: **After a successful recharge**, **Three days before expiry**, **When service expires**.
6. Open **ISP card → customer details → Customer WhatsApp**. After obtaining the customer's permission for service notifications, enable **Customer agreed to WhatsApp notifications**. Only customers with an enabled enrollment and valid saved phone receive messages. Use this same control to honor stop requests. AirLink does not currently receive inbound WhatsApp messages or automatically process replies such as STOP.

Owner-only account configuration is enforced by the API. Owners and staff with ISP card edit permission may enable or disable customers they can access in SAS4. Both the staff and selected owner's SAS4 customer identity and saved phone must match at enrollment. Account or phone changes invalidate the enrollment. Selecting another owner or disconnecting requires enrollment under the selected sender.

## Templates

Suggested English bodies (submit these yourself for Meta approval):

| Template name | Body | Variables |
| --- | --- | --- |
| `airlink_recharge` | Your internet account {{1}} was recharged successfully. New service expiry: {{2}}. Transaction reference: {{3}}. | Account, new expiry, transaction reference |
| `airlink_expiry_3days` | Your internet account {{1}} will expire in three days, on {{2}}. Please contact us if you need to renew. | Account, expiry |
| `airlink_expired` | Your internet account {{1}} expired on {{2}}. Please contact us if you need to renew. | Account, expiry |

Use exactly the language code approved for all three templates, for example `en_US` or `ar`. Meta decides approval, supported languages, pricing and delivery limits. AirLink does not translate or submit these templates. A successful connection check does not guarantee later delivery if Meta pauses a template or restricts an account.

## Behavior and status

- Confirmed card PIN, balance, service extension, FIB and FastPay recharges in AirLink queue one receipt per transaction. Failed/unconfirmed recharges do not queue receipts. Recharges performed directly in another SAS4 application are not observed as recharge events; expiry is still checked from SAS4.
- The background worker checks enrolled customers in due order, one customer per five-second worker cycle. After a successful check, that customer is due again in one hour. Large queues and SAS4 response times can extend this interval. Before sending, AirLink rechecks access, customer identity, phone, enrollment and current expiry.
- The three-day reminder is eligible when expiry is more than 48 and at most 72 hours away. An expiry notice is eligible during the first 24 hours after expiry. Each is queued once per customer and expiry timestamp. Renewed, disabled or stale expiry notices are cancelled. The scanner does not send a backlog of notices for accounts expired longer than 24 hours.
- A missing/invalid expiry prevents a message rather than inventing a date. Pending receipts older than 24 hours are cancelled. Account and recipient selection changes cancel incompatible queued messages.
- Notification errors never retry the recharge itself. A provider cooldown delays pending messages, with at most five send attempts. A transport timeout, server error or process interruption after submission begins is **unconfirmed** and is not automatically resent, avoiding duplicate messages. Check WhatsApp Manager before taking further action.
- **accepted** means Meta returned a message ID. It does not mean delivered or read. Delivery/read webhook processing is not included. Recent statuses are visible in owner settings and the customer panel for 90 days.
- Sending and connection checks use outbound HTTPS; an inbound webhook/callback domain is not required for this integration. No live WhatsApp messages are sent merely by opening a settings page, checking credentials, or enabling the feature; customer messages are sent by the enabled event triggers.
- Disconnect removes the saved token and customer enrollments, and cancels queued messages. Encrypted application backups include this configuration with the database and encryption key; protect backup passwords accordingly.

Official API references: [Cloud API overview](https://developers.facebook.com/documentation/business-messaging/whatsapp/overview), [template requirements and sending format](https://developers.facebook.com/documentation/business-messaging/whatsapp/templates/overview/).
