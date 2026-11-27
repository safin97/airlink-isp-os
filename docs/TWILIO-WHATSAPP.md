# Twilio WhatsApp messaging

Open **My account → Twilio WhatsApp messaging**. Connect your SAS4 account first, then enter your Twilio Account SID and Auth Token. Choose either a WhatsApp-enabled sender number in international format (`+` and country code), or a Messaging Service SID whose sender pool contains your WhatsApp sender. Leave the other sender field blank. AirLink adds `whatsapp:` when sending; it does not fall back to SMS.

Create three **text** templates in Twilio Content Template Builder and obtain WhatsApp approval. Select the language there. Paste each template's **HX Content SID** into AirLink:

| Event | Template variables |
| --- | --- |
| Successful recharge | `{{1}}` customer account, `{{2}}` new service expiry, `{{3}}` transaction reference |
| Three days before expiry | `{{1}}` customer account, `{{2}}` service expiry |
| Service expired | `{{1}}` customer account, `{{2}}` service expiry |

Use `twilio/text` templates with the listed variables and no additional media, header or button content. Unicode variable values are preserved; choose a template language supported by Twilio and WhatsApp. AirLink supplies the actual account, expiry and transaction values; it never includes passwords or recharge PINs.

1. Save the connection and Content SIDs with all notification switches off.
2. Select **Check connection and templates**. This checks the active Twilio account, Messaging Service ownership when selected, template account, WhatsApp approval and expected variables. It does not send a test message. Configure and approve the sender itself in Twilio Console; this check does not prove sender readiness or recipient delivery.
3. Enable the recharge and expiry events you want, then save.
4. Open an ISP card customer's **Customer WhatsApp** page and confirm permission for the new Twilio connection. The recipient comes from the saved SAS4 phone number. International numbers and Iraqi local mobile notation are normalized; for example, `07501234567` becomes `whatsapp:+9647501234567` when sending.

The direct Meta integration is retired. Installed upgrades preserve its history and encrypted settings, cancel its pending notifications, and disable its old enrollments. Twilio credentials and customer enrollments start separately; old Meta tokens are never used for Twilio. Existing WhatsApp administrator grants are retained, with separate View, Edit and Delete controls. Customer enrollment also requires ISP Card view/edit access. Changing a customer's phone or account requires permission again.

Only a confirmed recharge queues a receipt. Account scope, customer identity, settings and permissions are checked again before delivery. Credentials and queued payloads are encrypted. Accepted messages are distinguished from delivered messages; AirLink polls Twilio receipts for up to 24 hours without requiring an inbound webhook. An uncertain submission is not automatically repeated. Explicit rate limits use a bounded cooldown. Review Twilio Messaging logs for unresolved delivery results.

Background processing requires the installed services or local live launcher to remain running. Twilio and WhatsApp account, sender, template and messaging charges/restrictions apply. This integration expects approved Content templates; free-form messages and the Sandbox's inbound conversation flow are not used. Enter credentials in the dashboard, not in source code.

Tests use simulated provider responses. Real delivery requires an eligible Twilio WhatsApp sender, approved templates, valid credentials and customer enrollment.

Provider references: [WhatsApp template notifications](https://www.twilio.com/docs/whatsapp/tutorial/send-whatsapp-notification-messages-templates), [ContentSid and ContentVariables requests](https://www.twilio.com/docs/content/send-templates-created-with-the-content-template-builder), [Content API and approval status](https://www.twilio.com/docs/content/content-api-resources), [message delivery states](https://www.twilio.com/docs/messaging/api/message-resource).
