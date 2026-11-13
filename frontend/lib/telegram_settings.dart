import 'package:flutter/material.dart';
import 'api.dart';

class TelegramSettings extends StatefulWidget {
  final Api api;
  const TelegramSettings({super.key, required this.api});
  @override
  State<TelegramSettings> createState() => _TelegramSettingsState();
}

class _TelegramSettingsState extends State<TelegramSettings> {
  final token = TextEditingController();
  final chat = TextEditingController();
  bool enabled = false, busy = true, hasToken = false;
  String? message;
  Map<String, dynamic> saved = {};
  @override
  void initState() {
    super.initState();
    load();
  }

  Future<void> load() async {
    try {
      final result = await widget.api.request('/integrations/telegram');
      if (!mounted) return;
      saved = Map<String, dynamic>.from(result);
      enabled = saved['enabled'] == true;
      hasToken = saved['has_token'] == true;
      chat.text = saved['chat_id'] ?? '';
    } catch (e) {
      message = e.toString();
    }
    if (mounted) setState(() => busy = false);
  }

  Future<void> save({bool test = false}) async {
    setState(() {
      busy = true;
      message = null;
    });
    try {
      final result = await widget.api.request(
        '/integrations/telegram',
        method: 'PUT',
        body: {
          'enabled': enabled,
          'chat_id': chat.text.trim(),
          if (token.text.trim().isNotEmpty) 'bot_token': token.text.trim(),
        },
      );
      if (!mounted) return;
      saved = Map<String, dynamic>.from(result);
      hasToken = true;
      token.clear();
      if (test) {
        saved = Map<String, dynamic>.from(
          await widget.api.request(
            '/integrations/telegram/test',
            method: 'POST',
            retry: false,
          ),
        );
      }
      message = test ? 'Test notification sent.' : 'Telegram settings saved.';
    } catch (e) {
      message = e.toString();
    }
    if (mounted) setState(() => busy = false);
  }

  @override
  void dispose() {
    token.dispose();
    chat.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    children: [
      const Text(
        'Telegram notifications',
        style: TextStyle(fontSize: 24, fontWeight: FontWeight.w600),
      ),
      const SizedBox(height: 12),
      const Text(
        'Create a bot with @BotFather in Telegram. Start a chat with your bot, or add it to your group. Enter its token and the destination chat ID below. For a channel, you can use @channelname and grant the bot permission to post.',
      ),
      const SizedBox(height: 12),
      TextField(
        controller: token,
        obscureText: true,
        enableSuggestions: false,
        autocorrect: false,
        decoration: InputDecoration(
          labelText: 'Bot token',
          helperText: hasToken
              ? 'Token saved securely. Leave blank to keep it.'
              : 'Stored encrypted; never displayed after saving.',
        ),
      ),
      TextField(
        controller: chat,
        decoration: const InputDecoration(labelText: 'Chat ID or @channelname'),
      ),
      SwitchListTile(
        contentPadding: EdgeInsets.zero,
        title: const Text('Send device down and recovery notifications'),
        subtitle: const Text(
          'Runs in the background while the monitoring service is active.',
        ),
        value: enabled,
        onChanged: busy ? null : (value) => setState(() => enabled = value),
      ),
      Wrap(
        spacing: 12,
        runSpacing: 8,
        children: [
          FilledButton(
            onPressed: busy ? null : () => save(),
            child: const Text('Save'),
          ),
          OutlinedButton(
            onPressed: busy ? null : () => save(test: true),
            child: const Text('Save and send test'),
          ),
          TextButton(
            onPressed: busy
                ? null
                : () {
                    setState(() => busy = true);
                    load();
                  },
            child: const Text('Refresh status'),
          ),
        ],
      ),
      if (busy) const LinearProgressIndicator(),
      if (message != null)
        Padding(padding: const EdgeInsets.only(top: 12), child: Text(message!)),
      if (saved['last_error'] != null)
        Text('Last delivery error: ${saved['last_error']}'),
      if (saved['last_sent_at'] != null)
        Text('Last sent: ${saved['last_sent_at']}'),
    ],
  );
}
