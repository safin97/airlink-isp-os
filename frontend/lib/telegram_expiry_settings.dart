import 'package:flutter/material.dart';
import 'api.dart';

class TelegramExpirySettings extends StatefulWidget {
  const TelegramExpirySettings({super.key, required this.api});
  final Api api;
  @override
  State<TelegramExpirySettings> createState() => _TelegramExpirySettingsState();
}

class _TelegramExpirySettingsState extends State<TelegramExpirySettings> {
  bool busy = true, enabled = false;
  String? error, checked;
  static const path = '/integrations/recharge-telegram/expiry';
  @override
  void initState() {
    super.initState();
    run();
  }

  Future<void> run([bool? value]) async {
    setState(() {
      busy = true;
      error = null;
    });
    try {
      final result = await widget.api.request(
        path,
        method: value == null ? 'GET' : 'PUT',
        body: value == null ? null : {'enabled': value},
      );
      if (mounted) {
        enabled = result['enabled'] == true;
        error = result['last_error'];
        checked = result['last_checked'];
      }
    } catch (e) {
      if (mounted) error = e.toString();
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => Column(
    crossAxisAlignment: CrossAxisAlignment.stretch,
    children: [
      const Divider(),
      SwitchListTile(
        contentPadding: EdgeInsets.zero,
        title: const Text('Automatic expiry alerts'),
        value: enabled,
        onChanged: busy ? null : (value) => run(value),
      ),
      const Text(
        'Send once when service has 48–72 hours remaining and once during the first 24 hours after expiry. Checks the selected owner’s ISP customers in the background and skips renewed or disabled services. Older expired accounts are not notified.',
      ),
      const Text(
        'Uses the selected language and owner Telegram account. When enabled, this replaces the bot’s three-day reminder. Edit both messages under Edit notification message. Changing this switch saves immediately.',
      ),
      if (busy) const LinearProgressIndicator(),
      if (error != null)
        Text(
          error!,
          style: TextStyle(color: Theme.of(context).colorScheme.error),
        ),
      if (checked != null) Text('Last expiry check: $checked'),
      TextButton.icon(
        onPressed: busy ? null : () => run(),
        icon: const Icon(Icons.refresh),
        label: const Text('Refresh expiry check status'),
      ),
    ],
  );
}
