import 'package:flutter/material.dart';
import 'api.dart';

class NotificationMessageEditor extends StatefulWidget {
  const NotificationMessageEditor({
    super.key,
    required this.api,
    required this.language,
  });
  final Api api;
  final String language;
  @override
  State<NotificationMessageEditor> createState() =>
      _NotificationMessageEditorState();
}

class _NotificationMessageEditorState extends State<NotificationMessageEditor> {
  final text = TextEditingController();
  String kind = 'card';
  bool busy = true;
  String? error, notice, preview;
  List<String> placeholders = [];
  String get path =>
      '/integrations/recharge-telegram/templates/${widget.language}/$kind';
  static const kinds = {
    'card': 'Card PIN recharge',
    'credit': 'Balance recharge',
    'extend': 'Service extension',
    'fib': 'FIB recharge',
    'fastpay': 'FastPay recharge',
    'expiry_3days': 'Expires in 3 days',
    'expired': 'Service expired',
    'test': 'Phone test message',
  };

  @override
  void initState() {
    super.initState();
    run(load);
  }

  @override
  void dispose() {
    text.dispose();
    super.dispose();
  }

  void receive(dynamic result) {
    if (!mounted) return;
    text.text = result['text'] ?? '';
    preview = result['preview'];
    placeholders = List<String>.from(result['placeholders'] ?? []);
  }

  Future<void> load() async => receive(await widget.api.request(path));

  Future<void> run(Future<void> Function() action) async {
    setState(() {
      busy = true;
      error = null;
      notice = null;
    });
    try {
      await action();
    } catch (e) {
      if (mounted) error = e.toString();
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  void insert(String field) {
    final selection = text.selection;
    final start = selection.isValid ? selection.start : text.text.length;
    final end = selection.isValid ? selection.end : text.text.length;
    final value = '{$field}';
    text.value = TextEditingValue(
      text: text.text.replaceRange(start, end, value),
      selection: TextSelection.collapsed(offset: start + value.length),
    );
    setState(() => preview = null);
  }

  @override
  Widget build(BuildContext context) => ExpansionTile(
    title: const Text('Edit notification message'),
    subtitle: Text(
      'Language: ${const {'en': 'English', 'ku': 'Kurdish (Badini)', 'ar': 'Arabic'}[widget.language] ?? widget.language}',
    ),
    childrenPadding: const EdgeInsets.all(12),
    expandedCrossAxisAlignment: CrossAxisAlignment.stretch,
    children: [
      const Text(
        'Edit the messages sent from your connected Telegram account. Save your edits before changing language or message type.',
      ),
      const SizedBox(height: 12),
      DropdownButtonFormField<String>(
        initialValue: kind,
        key: ValueKey(kind),
        decoration: const InputDecoration(labelText: 'Message type'),
        items: kinds.entries
            .map(
              (entry) =>
                  DropdownMenuItem(value: entry.key, child: Text(entry.value)),
            )
            .toList(),
        onChanged: busy
            ? null
            : (value) => run(() async {
                kind = value!;
                preview = null;
                await load();
              }),
      ),
      if (busy) const LinearProgressIndicator(),
      if (error != null)
        Text(
          error!,
          style: TextStyle(color: Theme.of(context).colorScheme.error),
        ),
      if (notice != null) Text(notice!),
      const SizedBox(height: 12),
      TextField(
        controller: text,
        enabled: !busy,
        minLines: 6,
        maxLines: 12,
        maxLength: 1500,
        textDirection: widget.language == 'en'
            ? TextDirection.ltr
            : TextDirection.rtl,
        decoration: const InputDecoration(
          labelText: 'Notification text',
          border: OutlineInputBorder(),
        ),
        onChanged: (_) => setState(() => preview = null),
      ),
      const Text(
        'Tap to insert a detail. {recharge_cost} is the SAS4 manager recharge cost; use {currency} for its currency. {details} includes all available recharge details. Missing values are left blank. {card} contains only a masked card number.',
      ),
      Wrap(
        spacing: 6,
        runSpacing: 4,
        children: [
          for (final field in placeholders)
            ActionChip(
              label: Text('{$field}'),
              onPressed: busy ? null : () => insert(field),
            ),
        ],
      ),
      const SizedBox(height: 12),
      Wrap(
        spacing: 10,
        runSpacing: 8,
        children: [
          OutlinedButton(
            onPressed: busy
                ? null
                : () => run(() async {
                    final result = await widget.api.request(
                      '$path/preview',
                      method: 'POST',
                      body: {'text': text.text},
                    );
                    if (mounted) preview = result['preview'];
                  }),
            child: const Text('Preview message'),
          ),
          FilledButton(
            onPressed: busy
                ? null
                : () => run(() async {
                    receive(
                      await widget.api.request(
                        path,
                        method: 'PUT',
                        body: {'text': text.text},
                      ),
                    );
                    if (mounted) notice = 'Notification message saved.';
                  }),
            child: const Text('Save message'),
          ),
          TextButton(
            onPressed: busy
                ? null
                : () => run(() async {
                    receive(await widget.api.request(path, method: 'DELETE'));
                    if (mounted) {
                      notice = 'Default notification message restored.';
                    }
                  }),
            child: const Text('Restore default'),
          ),
        ],
      ),
      if (preview != null) ...[
        const SizedBox(height: 12),
        const Text(
          'Preview with sample details — no message is sent',
          style: TextStyle(fontWeight: FontWeight.w700),
        ),
        const SizedBox(height: 8),
        SelectableText(
          preview!,
          textDirection: widget.language == 'en'
              ? TextDirection.ltr
              : TextDirection.rtl,
        ),
      ],
    ],
  );
}
