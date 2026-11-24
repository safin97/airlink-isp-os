import 'section_access.dart';
import 'package:flutter/material.dart';
import 'api.dart';
import 'telegram_messages.dart';

class TelegramSettings extends StatefulWidget {
  final Api api;
  final String basePath;
  const TelegramSettings({
    super.key,
    required this.api,
    this.basePath = '/integrations/telegram',
  });
  @override
  State<TelegramSettings> createState() => _TelegramSettingsState();
}

class _TelegramSettingsState extends State<TelegramSettings> {
  final token = TextEditingController();
  final chat = TextEditingController();
  bool get canEdit =>
      canEditSection(widget.api.user ?? {}, 'telegram_notifications');
  bool editingMessages = false;
  bool enabled = false, busy = true, hasToken = false;
  bool languageDirty = false;
  String language = 'en';
  Map<String, dynamic> messageSettings = {};
  Map<String, dynamic> languages = {};
  String? message;
  Map<String, dynamic> saved = {};
  @override
  void initState() {
    super.initState();
    load();
  }

  Future<void> load() async {
    try {
      final result = await widget.api.request(widget.basePath);
      if (!mounted) return;
      saved = Map<String, dynamic>.from(result);
      enabled = saved['enabled'] == true;
      hasToken = saved['has_token'] == true;
      chat.text = saved['chat_id'] ?? '';
      await loadMessages();
    } catch (e) {
      message = e.toString();
    }
    if (mounted) setState(() => busy = false);
  }

  Future<void> loadMessages() async {
    final result = await widget.api.request('${widget.basePath}/messages');
    if (!mounted) return;
    messageSettings = Map<String, dynamic>.from(result);
    language = messageSettings['language'] ?? 'en';
    languages = Map<String, dynamic>.from(messageSettings['languages'] ?? {});
    languageDirty = false;
  }

  void chooseLanguage(String? value) {
    if (value == null || value == language) return;
    setState(() {
      final previousDefault = messageSettings['default_message'];
      final nextDefault = languages[value]['default_message'];
      for (final field in ['down_message', 'recovery_message']) {
        if (messageSettings[field] == previousDefault) {
          messageSettings[field] = nextDefault;
        }
      }
      messageSettings['default_message'] = nextDefault;
      language = value;
      languageDirty = true;
      message = null;
    });
  }

  Future<void> saveLanguage() async {
    if (!languageDirty) return;
    await widget.api.request(
      '${widget.basePath}/messages',
      method: 'PUT',
      body: {
        'language': language,
        'down_message': messageSettings['down_message'],
        'recovery_message': messageSettings['recovery_message'],
      },
    );
    languageDirty = false;
  }

  Future<void> showMessages(bool show) async {
    setState(() {
      busy = true;
      message = null;
    });
    try {
      if (show) {
        await saveLanguage();
      } else {
        await loadMessages();
      }
      if (mounted) setState(() => editingMessages = show);
    } catch (e) {
      if (mounted) setState(() => message = e.toString());
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> save({bool test = false}) async {
    setState(() {
      busy = true;
      message = null;
    });
    try {
      final result = await widget.api.request(
        widget.basePath,
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
      await saveLanguage();
      if (test) {
        saved = Map<String, dynamic>.from(
          await widget.api.request(
            '${widget.basePath}/test',
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
  Widget build(BuildContext context) => editingMessages
      ? Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            TextButton.icon(
              onPressed: busy ? null : () => showMessages(false),
              icon: const Icon(Icons.arrow_back),
              label: const Text('Back to Telegram connection'),
            ),
            const SizedBox(height: 12),
            TelegramMessages(api: widget.api, basePath: widget.basePath),
            if (busy) const LinearProgressIndicator(),
            if (message != null) Text(message!),
          ],
        )
      : Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text(
              'Telegram notifications',
              style: TextStyle(fontSize: 24, fontWeight: FontWeight.w600),
            ),
            const SizedBox(height: 12),
            OutlinedButton.icon(
              onPressed: !canEdit || busy || languages.isEmpty
                  ? null
                  : () => showMessages(true),
              icon: const Icon(Icons.edit_note),
              label: const Text('Next: Edit messages'),
            ),
            const SizedBox(height: 12),
            const Text(
              'Create a bot with @BotFather in Telegram. Start a chat with your bot, or add it to your group. Enter its token and the destination chat ID below. For a channel, you can use @channelname and grant the bot permission to post.',
            ),
            const SizedBox(height: 12),
            TextField(
              controller: token,
              enabled: canEdit && !busy,
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
              enabled: canEdit && !busy,
              decoration: const InputDecoration(
                labelText: 'Chat ID or @channelname',
              ),
            ),
            const SizedBox(height: 16),
            if (languages.isNotEmpty)
              DropdownButtonFormField<String>(
                key: ValueKey('telegram-language-$language'),
                initialValue: language,
                decoration: const InputDecoration(
                  labelText: 'Notification language',
                  helperText:
                      'Language used for Telegram alerts and test messages.',
                  border: OutlineInputBorder(),
                ),
                items: languages.entries
                    .map(
                      (entry) => DropdownMenuItem(
                        value: entry.key,
                        child: Text(entry.value['label'] as String),
                      ),
                    )
                    .toList(),
                onChanged: !canEdit || busy ? null : chooseLanguage,
              ),
            const SizedBox(height: 8),
            const Text(
              'Default messages follow this language. To translate custom wording, '
              'open Edit messages and use Restore defaults. Continuing to Edit '
              'messages also saves your language choice.',
            ),
            SwitchListTile(
              contentPadding: EdgeInsets.zero,
              title: const Text('Send device down and recovery notifications'),
              subtitle: const Text(
                'Runs in the background while the monitoring service is active.',
              ),
              value: enabled,
              onChanged: !canEdit || busy
                  ? null
                  : (value) => setState(() => enabled = value),
            ),
            Wrap(
              spacing: 12,
              runSpacing: 8,
              children: [
                FilledButton(
                  onPressed: !canEdit || busy || languages.isEmpty
                      ? null
                      : () => save(),
                  child: const Text('Save'),
                ),
                OutlinedButton(
                  onPressed: !canEdit || busy || languages.isEmpty
                      ? null
                      : () => save(test: true),
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
              Padding(
                padding: const EdgeInsets.only(top: 12),
                child: Text(message!),
              ),
            if (saved['last_error'] != null)
              Text('Last delivery error: ${saved['last_error']}'),
            if (saved['last_sent_at'] != null)
              Text('Last sent: ${saved['last_sent_at']}'),
          ],
        );
}
