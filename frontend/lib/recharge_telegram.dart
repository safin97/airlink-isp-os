import 'package:flutter/material.dart';
import 'api.dart';
import 'notification_message_editor.dart';
import 'telegram_expiry_settings.dart';

class RechargeTelegramSettings extends StatefulWidget {
  const RechargeTelegramSettings({super.key, required this.api});
  final Api api;
  @override
  State<RechargeTelegramSettings> createState() =>
      _RechargeTelegramSettingsState();
}

class _RechargeTelegramSettingsState extends State<RechargeTelegramSettings> {
  final timezone = TextEditingController(text: 'Asia/Baghdad');
  bool busy = true, enabled = false, selectedOwner = false;
  String language = 'en';
  String? error, message;
  static const path = '/integrations/recharge-telegram';

  @override
  void initState() {
    super.initState();
    run(load);
  }

  @override
  void dispose() {
    timezone.dispose();
    super.dispose();
  }

  Future<void> load() async {
    final data = await widget.api.request(path);
    if (!mounted) return;
    enabled = data['enabled'] == true;
    selectedOwner = data['selected_owner'] == true;
    language = data['language'] ?? 'en';
    timezone.text = data['timezone'] ?? 'Asia/Baghdad';
  }

  Future<void> run(Future<void> Function() action) async {
    setState(() {
      busy = true;
      error = null;
      message = null;
    });
    try {
      await action();
    } catch (e) {
      if (mounted) error = e.toString();
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> changeLanguage(String value) async {
    final previous = language;
    setState(() => language = value);
    try {
      await widget.api.request(
        '$path/language',
        method: 'PUT',
        body: {'language': value},
      );
      if (mounted) message = 'Language saved for all ISP card customers.';
    } catch (_) {
      if (mounted) language = previous;
      rethrow;
    }
  }

  @override
  Widget build(BuildContext context) => Card(
    child: Padding(
      padding: const EdgeInsets.all(20),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          const Text(
            'Automatic recharge notifications',
            style: TextStyle(fontWeight: FontWeight.w700),
          ),
          const SizedBox(height: 8),
          const Text(
            'After a successful card PIN, balance, extension, FIB or FastPay recharge by an owner or manager, send a Telegram receipt to the account matched to the customer’s saved phone. Receipts include available plan, expiry, price and transaction details. Card PINs are masked.',
          ),
          const Text(
            'Messages come from the selected owner’s connected Telegram user account. Telegram privacy settings may prevent delivery. When enabled, this replaces owner-bot recharge messages. Expiry alerts have their own switch below.',
          ),
          if (busy) const LinearProgressIndicator(),
          if (error != null)
            Text(
              error!,
              style: TextStyle(color: Theme.of(context).colorScheme.error),
            ),
          if (message != null) Text(message!),
          if (enabled && !selectedOwner)
            const Text(
              'Another owner account is currently selected. Saving enabled settings selects your connected account.',
            ),
          SwitchListTile(
            contentPadding: EdgeInsets.zero,
            title: const Text('Send after every successful recharge'),
            value: enabled,
            onChanged: busy ? null : (value) => setState(() => enabled = value),
          ),
          DropdownButtonFormField<String>(
            key: ValueKey(language),
            initialValue: language,
            decoration: const InputDecoration(
              labelText: 'Language for all ISP card customers',
              helperText:
                  'Saved immediately. Applies to customer notifications and tests.',
            ),
            items: const [
              DropdownMenuItem(value: 'en', child: Text('English')),
              DropdownMenuItem(value: 'ku', child: Text('کوردی (بادینی)')),
              DropdownMenuItem(value: 'ar', child: Text('العربية')),
            ],
            onChanged: busy
                ? null
                : (value) => run(() => changeLanguage(value!)),
          ),
          TextField(
            controller: timezone,
            enabled: !busy,
            decoration: const InputDecoration(
              labelText: 'SAS4 expiry timezone',
            ),
          ),
          NotificationMessageEditor(
            key: ValueKey('message-$language'),
            api: widget.api,
            language: language,
          ),
          const SizedBox(height: 12),
          FilledButton(
            onPressed: busy
                ? null
                : () => run(() async {
                    await widget.api.request(
                      path,
                      method: 'PUT',
                      body: {
                        'enabled': enabled,
                        'language': language,
                        'timezone': timezone.text.trim(),
                      },
                    );
                    await load();
                    if (mounted) {
                      message = enabled
                          ? 'Automatic recharge notifications enabled from your Telegram account.'
                          : 'Automatic account recharge notifications disabled.';
                    }
                  }),
            child: const Text('Save recharge notifications'),
          ),
          TelegramExpirySettings(api: widget.api),
        ],
      ),
    ),
  );
}
