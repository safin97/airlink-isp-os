import 'package:flutter/material.dart';
import 'api.dart';

class TelegramMessages extends StatefulWidget {
  final Api api;
  final String basePath;
  const TelegramMessages({
    super.key,
    required this.api,
    this.basePath = '/integrations/telegram',
  });
  @override
  State<TelegramMessages> createState() => _TelegramMessagesState();
}

class _TelegramMessagesState extends State<TelegramMessages> {
  final down = TextEditingController();
  final recovery = TextEditingController();
  bool busy = true, loaded = false;
  String defaultMessage = '';
  String language = 'en';
  Map<String, dynamic> languages = {};
  String? message;
  List<String> placeholders = [];

  @override
  void initState() {
    super.initState();
    load();
  }

  Future<void> load() async {
    try {
      final data = await widget.api.request('${widget.basePath}/messages');
      if (!mounted) return;
      down.text = data['down_message'];
      recovery.text = data['recovery_message'];
      defaultMessage = data['default_message'];
      language = data['language'] ?? 'en';
      languages = Map<String, dynamic>.from(data['languages'] ?? {});
      placeholders = List<String>.from(data['placeholders']);
      loaded = true;
    } catch (e) {
      message = e.toString();
    }
    if (mounted) setState(() => busy = false);
  }

  Future<void> save() async {
    setState(() {
      busy = true;
      message = null;
    });
    try {
      await widget.api.request(
        '${widget.basePath}/messages',
        method: 'PUT',
        body: {
          'language': language,
          'down_message': down.text,
          'recovery_message': recovery.text,
        },
      );
      if (mounted) {
        setState(
          () => message =
              'Messages saved for your account. New alerts will use these messages.',
        );
      }
    } catch (e) {
      if (mounted) setState(() => message = e.toString());
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  String preview(String template, bool recovered) {
    final localized = languages[language];
    final values = {
      'status':
          localized?[recovered ? 'recovery_status' : 'down_status'] ??
          (recovered ? 'RECOVERED' : 'DOWN / TIMEOUT'),
      'device_name': 'Example router',
      'ip_address': '192.0.2.10',
      'tower_name': 'Example tower',
      'time': '2026-11-14T12:00:00+00:00',
    };
    return template.replaceAllMapped(
      RegExp(r'\{([^{}]*)\}'),
      (match) => (values[match[1]] ?? match[0]!).toString(),
    );
  }

  void changeLanguage(String? value) {
    if (value == null || value == language) return;
    setState(() {
      final nextDefault = languages[value]['default_message'] as String;
      if (down.text == defaultMessage) down.text = nextDefault;
      if (recovery.text == defaultMessage) recovery.text = nextDefault;
      language = value;
      defaultMessage = nextDefault;
      message =
          'Language changed. Custom wording is kept; use Restore defaults '
          'to load translated messages. Save messages to apply.';
    });
  }

  TextDirection get messageDirection => languages[language]?['rtl'] == true
      ? TextDirection.rtl
      : TextDirection.ltr;

  Widget editor(
    String title,
    TextEditingController controller,
    bool recovered,
  ) => Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    children: [
      TextField(
        controller: controller,
        textDirection: messageDirection,
        enabled: !busy,
        minLines: 4,
        maxLines: 10,
        maxLength: 1000,
        decoration: InputDecoration(
          labelText: title,
          border: const OutlineInputBorder(),
        ),
        onChanged: (_) => setState(() {}),
      ),
      const Text(
        'Preview · sample device',
        style: TextStyle(fontWeight: FontWeight.w600),
      ),
      const SizedBox(height: 8),
      Container(
        width: double.infinity,
        padding: const EdgeInsets.all(16),
        decoration: BoxDecoration(
          color: Theme.of(context).colorScheme.surfaceContainerHighest,
          borderRadius: BorderRadius.circular(12),
        ),
        child: SelectableText(
          preview(controller.text, recovered),
          textDirection: messageDirection,
        ),
      ),
      const SizedBox(height: 24),
    ],
  );

  @override
  void dispose() {
    down.dispose();
    recovery.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    children: [
      const Text(
        'Edit notification messages',
        style: TextStyle(fontSize: 24, fontWeight: FontWeight.w600),
      ),
      const SizedBox(height: 12),
      const Text(
        'Customize your device-down and recovery messages. Placeholders are filled with the device details when an alert occurs. Messages are sent as plain text; times use UTC.',
      ),
      const SizedBox(height: 8),
      SelectableText(placeholders.map((key) => '{$key}').join('  ')),
      const SizedBox(height: 20),
      if (loaded) ...[
        if (languages.isNotEmpty) ...[
          DropdownButtonFormField<String>(
            initialValue: language,
            decoration: const InputDecoration(
              labelText: 'Notification language',
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
            onChanged: busy ? null : changeLanguage,
          ),
          const SizedBox(height: 20),
        ],
        editor('Device down / timeout message', down, false),
        editor('Recovery message', recovery, true),
        Wrap(
          spacing: 12,
          runSpacing: 8,
          children: [
            FilledButton(
              onPressed: busy ? null : save,
              child: const Text('Save messages'),
            ),
            OutlinedButton(
              onPressed: busy
                  ? null
                  : () => setState(() {
                      down.text = defaultMessage;
                      recovery.text = defaultMessage;
                      message =
                          'Defaults restored in the editor. Save messages to apply.';
                    }),
              child: const Text('Restore defaults'),
            ),
          ],
        ),
      ],
      if (busy) const LinearProgressIndicator(),
      if (message != null)
        Padding(padding: const EdgeInsets.only(top: 12), child: Text(message!)),
      if (!loaded && !busy)
        TextButton(
          onPressed: () {
            setState(() => busy = true);
            load();
          },
          child: const Text('Retry'),
        ),
    ],
  );
}
