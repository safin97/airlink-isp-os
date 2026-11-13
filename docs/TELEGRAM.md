# Telegram notifications

Owners and managers can configure **My account → Telegram notifications**. Each account has its own encrypted bot token, destination, enable switch and delivery status. Notifications are restricted to devices visible to that account, and permissions are checked again before delivery. Create a bot through Telegram's verified @BotFather, start a conversation with the bot (or add it to a group), and enter the bot token and destination chat ID. A public channel can use @channelname; the bot needs permission to post there. For a numeric chat ID, Telegram's getUpdates method returns message.chat.id after a message is sent to the bot; keep requests containing the bot token private. Do not share the token in screenshots or support messages.

Save the settings and use **Save and send test** to verify delivery. Enable **Send device down and recovery notifications** for automatic alerts. Tokens are encrypted at rest and are never returned by the settings API. Each owner or manager can read and change only their own settings and send tests only to their own saved destination.

The alert service sends a notification when an enabled inventory device crosses its configured availability failure threshold, and another when an active down incident resolves with a fresh online reading. Existing incidents are not replayed when notifications are enabled. Unknown/stale telemetry is not described as recovered. The NOC page does not need to remain open. Internet access to api.telegram.org is required.

Notifications use a persistent queue, with up to five delivery attempts and increasing delays. After five failures, inspect the delivery error in Settings and use the test button after correcting the connection. Saving settings discards that account’s pending notifications so old events are not delivered to a different destination. Telegram does not offer an idempotency key for sendMessage; an ambiguous network failure or crash after delivery may produce a duplicate on retry. Successful queue records are retained for 30 days.

Installed systems use airlink-alerts.service. Local **live** mode also evaluates alerts and dispatches enabled Telegram notifications. Demo mode does not automatically dispatch alerts. No bot is connected or message sent simply by installing this feature.

API reference: https://core.telegram.org/bots/api#sendmessage
