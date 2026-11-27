import 'section_access.dart';
import 'package:flutter/material.dart';
import 'dart:async';
import 'dart:convert';
import 'api.dart';

const whatsappPath = '/integrations/twilio-whatsapp';
const whatsappKinds = {
  'recharge': 'After a successful recharge',
  'expiry_3days': 'Three days before expiry',
  'expired': 'When service expires',
};

Widget whatsappHistory(dynamic events) => Column(
  crossAxisAlignment: CrossAxisAlignment.stretch,
  children: [
    const SizedBox(height: 16),
    const Text(
      'Recent Twilio WhatsApp messaging',
      style: TextStyle(fontWeight: FontWeight.bold),
    ),
    if (events is! List || events.isEmpty) const Text('No notifications yet.'),
    if (events is List)
      for (final event in events)
        ListTile(
          contentPadding: EdgeInsets.zero,
          title: Text(
            '${whatsappKinds[event['kind']] ?? event['kind']} · ${event['status']}',
          ),
          subtitle: Text(
            '${event['created_at'] ?? ''}\n${event['detail'] ?? ''}',
          ),
        ),
  ],
);

class TwilioWhatsAppSettings extends StatefulWidget {
  const TwilioWhatsAppSettings({super.key, required this.api});
  final Api api;
  @override
  State<TwilioWhatsAppSettings> createState() => _TwilioWhatsAppSettingsState();
}

class _TwilioWhatsAppSettingsState extends State<TwilioWhatsAppSettings> {
  final fields = <String, TextEditingController>{
    for (final key in [
      'account_sid',
      'from_number',
      'messaging_service_sid',
      'timezone',
      'recharge_content_sid',
      'expiry_3days_content_sid',
      'expired_content_sid',
    ])
      key: TextEditingController(),
  };
  final token = TextEditingController();
  Map data = {};
  final enabled = <String, bool>{
    for (final kind in whatsappKinds.keys) kind: false,
  };
  bool busy = true, dirty = false;
  bool fetching = false;
  int generation = 0;
  Timer? refreshTimer;
  String? error, message;

  @override
  void initState() {
    super.initState();
    run(load);
    refreshTimer = Timer.periodic(
      const Duration(seconds: 5),
      (_) => refreshStatus(),
    );
  }

  @override
  void dispose() {
    refreshTimer?.cancel();
    for (final field in fields.values) {
      field.dispose();
    }
    token.dispose();
    super.dispose();
  }

  Future<void> load() async {
    final result = await widget.api.request(whatsappPath);
    if (!mounted) return;
    data = Map.from(result);
    for (final entry in fields.entries) {
      entry.value.text = '${data[entry.key] ?? ''}';
    }
    for (final kind in enabled.keys) {
      enabled[kind] = data[kind] == true;
    }
    token.clear();
    dirty = false;
  }

  Future<void> run(Future<void> Function() action) async {
    generation++;
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

  Future<void> refreshStatus() async {
    if (busy || fetching) return;
    fetching = true;
    final request = generation;
    try {
      final result = await widget.api.request(whatsappPath);
      if (mounted &&
          request == generation &&
          jsonEncode(data) != jsonEncode(result)) {
        // Only status/history changes here. Keep all unsaved account fields.
        setState(() => data = Map.from(result));
      }
    } catch (_) {
      // A failed background read must not erase the owner's configuration draft.
    } finally {
      fetching = false;
    }
  }

  Widget field(String key, String label, {String? help, int lines = 1}) =>
      Padding(
        padding: const EdgeInsets.only(top: 14),
        child: TextField(
          controller: fields[key],
          minLines: lines,
          maxLines: lines == 1 ? 1 : 6,
          enabled: !busy && canEditSection(widget.api.user ?? {}, 'whatsapp'),
          onChanged: (_) => setState(() => dirty = true),
          decoration: InputDecoration(
            labelText: label,
            helperText: help,
            helperMaxLines: 4,
          ),
        ),
      );

  Future<void> save() async {
    await widget.api.request(
      whatsappPath,
      method: 'PUT',
      body: {
        for (final entry in fields.entries) entry.key: entry.value.text.trim(),
        'auth_token': token.text.trim(),
        ...enabled,
      },
    );
    await load();
    if (mounted) message = 'Twilio WhatsApp settings saved.';
  }

  @override
  Widget build(BuildContext context) => Column(
    crossAxisAlignment: CrossAxisAlignment.stretch,
    children: [
      const Text(
        'Twilio WhatsApp messaging',
        style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold),
      ),
      const SizedBox(height: 8),
      const Text(
        'Send WhatsApp to ISP card customers after recharge, three days before expiry, and when service expires.',
      ),
      const Text(
        '1. Save your Twilio details with notifications off.\n2. Check the connection and templates.\n3. Enable the notifications below and save.\n4. Open each ISP card customer → Customer WhatsApp to record permission and enable messages.',
      ),
      if (busy) const LinearProgressIndicator(),
      if (error != null)
        Text(
          error!,
          style: TextStyle(color: Theme.of(context).colorScheme.error),
        ),
      if (message != null) Text(message!),
      if (data['token_saved'] == true && data['selected_owner'] != true)
        const Text(
          'Another account is selected. Enter your own Twilio Auth Token to select your SAS4 account.',
        ),
      Text(
        data['verified_at'] != null
            ? 'Connection and templates checked: ${data['verified_at']}'
            : 'Connection and templates have not been checked.',
      ),
      if (data['token_saved'] == true && data['account_ready'] != true)
        const Text('Reconnect the selected owner SAS4 account before sending.'),
      if (data['retry_at'] != null)
        Text('Provider cooldown until: ${data['retry_at']}'),
      if (data['last_error'] != null) Text('${data['last_error']}'),
      field(
        'account_sid',
        'Twilio Account SID',
        help: 'Starts with AC. Use the account that owns your WhatsApp sender.',
      ),
      field(
        'from_number',
        'Twilio WhatsApp sender number',
        help:
            'Use a WhatsApp-enabled sender in Twilio Console, for example +15551234567. Leave blank for a Messaging Service.',
      ),
      field(
        'messaging_service_sid',
        'Messaging Service SID (optional)',
        help:
            'Starts with MG. Use this instead of a phone number, with a WhatsApp sender in its pool.',
      ),
      const SizedBox(height: 14),
      TextField(
        controller: token,
        enabled: !busy && canEditSection(widget.api.user ?? {}, 'whatsapp'),
        obscureText: true,
        autocorrect: false,
        enableSuggestions: false,
        onChanged: (_) => setState(() => dirty = true),
        decoration: InputDecoration(
          labelText: 'Twilio Auth Token',
          helperText: data['token_saved'] == true
              ? 'Leave blank to keep your saved token.'
              : 'Find the Auth Token in Twilio Console. It is stored encrypted.',
        ),
      ),
      field('timezone', 'SAS4 expiry timezone'),
      const SizedBox(height: 20),
      const Text(
        'Create and approve three text templates in Twilio Content Template Builder, then paste their HX Content SIDs below. The template controls the message text and language. Your Twilio sender must be enabled for WhatsApp; provider messaging charges apply.',
      ),
      for (final entry in whatsappKinds.entries) ...[
        field(
          '${entry.key}_content_sid',
          '${entry.value} · Content SID',
          help: entry.key == 'recharge'
              ? 'HX… template: {{1}} = account, {{2}} = expiry, {{3}} = transaction reference.'
              : 'HX… template: {{1}} = account, {{2}} = service expiry.',
        ),
        SwitchListTile(
          contentPadding: EdgeInsets.zero,
          title: Text(entry.value),
          value: enabled[entry.key]!,
          onChanged: busy || !canEditSection(widget.api.user ?? {}, 'whatsapp')
              ? null
              : (value) => setState(() {
                  enabled[entry.key] = value;
                  dirty = true;
                }),
        ),
      ],
      const SizedBox(height: 12),
      Wrap(
        spacing: 12,
        runSpacing: 12,
        children: [
          FilledButton(
            onPressed:
                !canEditSection(widget.api.user ?? {}, 'whatsapp') || busy
                ? null
                : () => run(save),
            child: const Text('Save Twilio WhatsApp settings'),
          ),
          OutlinedButton(
            onPressed:
                !canEditSection(widget.api.user ?? {}, 'whatsapp') ||
                    busy ||
                    dirty ||
                    data['token_saved'] != true
                ? null
                : () => run(() async {
                    await widget.api.request(
                      '$whatsappPath/check',
                      method: 'POST',
                    );
                    await load();
                    if (mounted) {
                      message =
                          'Twilio account and WhatsApp templates checked. No message was sent.';
                    }
                  }),
            child: const Text('Check connection and templates'),
          ),
          OutlinedButton(
            onPressed: busy ? null : () => run(load),
            child: const Text('Refresh status'),
          ),
          TextButton(
            onPressed:
                !canDeleteSection(widget.api.user ?? {}, 'whatsapp') ||
                    busy ||
                    data['token_saved'] != true
                ? null
                : () async {
                    final confirmed = await showDialog<bool>(
                      context: context,
                      builder: (context) => AlertDialog(
                        title: const Text('Disconnect WhatsApp?'),
                        content: const Text(
                          'Stops queued notifications, removes the saved Auth Token and clears customer enrollments. You will need to enable customers again after reconnecting.',
                        ),
                        actions: [
                          TextButton(
                            onPressed: () => Navigator.pop(context, false),
                            child: const Text('Cancel'),
                          ),
                          FilledButton(
                            onPressed: () => Navigator.pop(context, true),
                            child: const Text('Disconnect'),
                          ),
                        ],
                      ),
                    );
                    if (confirmed == true && mounted) {
                      run(() async {
                        await widget.api.request(
                          whatsappPath,
                          method: 'DELETE',
                        );
                        await load();
                      });
                    }
                  },
            child: const Text('Disconnect WhatsApp'),
          ),
        ],
      ),
      if (dirty)
        const Text(
          'Save changes before checking the connection. Turn notifications off before changing credentials, sender or Content SIDs.',
        ),
      whatsappHistory(data['events']),
    ],
  );
}

class CustomerWhatsApp extends StatefulWidget {
  const CustomerWhatsApp({
    super.key,
    required this.api,
    required this.customerId,
  });
  final Api api;
  final int customerId;
  @override
  State<CustomerWhatsApp> createState() => _CustomerWhatsAppState();
}

class _CustomerWhatsAppState extends State<CustomerWhatsApp> {
  Map data = {};
  bool busy = true;
  bool fetching = false;
  int generation = 0;
  Timer? refreshTimer;
  String? error;
  String get path => '$whatsappPath/users/${widget.customerId}';
  @override
  void initState() {
    super.initState();
    run();
    refreshTimer = Timer.periodic(
      const Duration(seconds: 5),
      (_) => run(quiet: true),
    );
  }

  @override
  void dispose() {
    refreshTimer?.cancel();
    super.dispose();
  }

  Future<void> run({bool? enabled, bool quiet = false}) async {
    if (quiet && (busy || fetching)) return;
    final request = ++generation;
    fetching = true;
    if (!quiet) {
      setState(() {
        busy = true;
        error = null;
      });
    }
    try {
      final result = await widget.api.request(
        path,
        method: enabled == null ? 'GET' : 'PUT',
        body: enabled == null ? null : {'enabled': enabled},
      );
      if (mounted &&
          request == generation &&
          (error != null || jsonEncode(data) != jsonEncode(result))) {
        setState(() {
          data = Map.from(result);
          error = null;
        });
      }
    } catch (e) {
      if (mounted && request == generation) {
        setState(() => error = e.toString());
      }
    } finally {
      if (request == generation) fetching = false;
      if (mounted && request == generation && busy) {
        setState(() => busy = false);
      }
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: AppBar(title: const Text('Customer WhatsApp')),
    body: SingleChildScrollView(
      padding: const EdgeInsets.all(24),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          if (busy) const LinearProgressIndicator(),
          if (error != null)
            Text(
              error!,
              style: TextStyle(color: Theme.of(context).colorScheme.error),
            ),
          Text('Saved customer phone: ${data['phone'] ?? 'No valid phone'}'),
          if (data['configured'] != true)
            const Text('Set up My account → Twilio WhatsApp messaging first.'),
          const SizedBox(height: 12),
          const Text(
            'Enable only after the customer agrees to receive service notifications on WhatsApp. Confirm permission again when switching from the previous Meta integration. Messages use the phone saved in ISP card. Turn this off when the customer asks to stop. A changed phone or customer account requires permission again.',
          ),
          SwitchListTile(
            contentPadding: EdgeInsets.zero,
            title: const Text('Customer agreed to WhatsApp notifications'),
            subtitle: const Text(
              'Recharge receipt, three-day reminder and expiry notice, as enabled by the owner.',
            ),
            value: data['enabled'] == true,
            onChanged:
                busy ||
                    !canEditSection(widget.api.user ?? {}, 'whatsapp') ||
                    !canEditSection(widget.api.user ?? {}, 'isp_card') ||
                    data['configured'] != true ||
                    data['phone'] == null
                ? null
                : (value) => run(enabled: value),
          ),
          if (data['consent_at'] != null)
            Text('Permission recorded: ${data['consent_at']}'),
          if (data['last_error'] != null) Text('${data['last_error']}'),
          OutlinedButton(
            onPressed: busy ? null : () => run(),
            child: const Text('Refresh status'),
          ),
          whatsappHistory(data['events']),
        ],
      ),
    ),
  );
}
