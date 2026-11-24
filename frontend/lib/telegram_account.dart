import 'section_access.dart';
import 'package:flutter/material.dart';
import 'api.dart';
import 'recharge_telegram.dart';
import 'telegram_cooldown.dart';

const telegramAccountPath = '/integrations/telegram-account';

class TelegramAccountSettings extends StatefulWidget {
  const TelegramAccountSettings({super.key, required this.api});
  final Api api;
  @override
  State<TelegramAccountSettings> createState() =>
      _TelegramAccountSettingsState();
}

class _TelegramAccountSettingsState extends State<TelegramAccountSettings>
    with TelegramCooldown<TelegramAccountSettings> {
  final apiId = TextEditingController();
  final apiHash = TextEditingController();
  final phone = TextEditingController();
  final code = TextEditingController();
  final password = TextEditingController();
  Map<String, dynamic> status = {};
  bool busy = true;
  String? error;
  String get stage => status['stage'] ?? 'disconnected';

  @override
  void initState() {
    super.initState();
    if (!hasSection(widget.api.user ?? {}, 'telegram_account')) return;
    run(
      () async => status = Map<String, dynamic>.from(
        await widget.api.request(telegramAccountPath),
      ),
    );
  }

  @override
  void dispose() {
    for (final controller in [apiId, apiHash, phone, code, password]) {
      controller.dispose();
    }
    super.dispose();
  }

  Future<void> run(Future<void> Function() action) async {
    if (coolingDown) return;
    setState(() {
      busy = true;
      error = null;
      cooldownNotice = false;
    });
    try {
      await action();
      if (mounted) acceptCooldown(status['retry_after_seconds']);
    } catch (e) {
      if (mounted && !acceptCooldownError(e)) {
        setState(() => error = e.toString());
      }
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> login() async {
    final body = {
      'api_id': int.tryParse(apiId.text.trim()),
      'api_hash': apiHash.text.trim(),
      'phone': phone.text.trim(),
    };
    status = Map<String, dynamic>.from(
      await widget.api.request(
        '$telegramAccountPath/login',
        method: 'POST',
        body: body,
      ),
    );
    if (mounted) {
      apiHash.clear();
      phone.clear();
    }
  }

  Future<void> verify() async {
    final body = stage == 'password'
        ? {'password': password.text}
        : {'code': code.text.trim()};
    try {
      final result = await widget.api.request(
        '$telegramAccountPath/verify',
        method: 'POST',
        body: body,
      );
      if (mounted) status = Map<String, dynamic>.from(result);
    } finally {
      if (mounted) {
        code.clear();
        password.clear();
      }
    }
  }

  Widget field(
    TextEditingController controller,
    String label, {
    bool secret = false,
    bool numeric = false,
  }) => Padding(
    padding: const EdgeInsets.only(bottom: 12),
    child: TextField(
      controller: controller,
      enabled: !busy,
      obscureText: secret,
      autocorrect: false,
      enableSuggestions: false,
      keyboardType: numeric ? TextInputType.number : TextInputType.text,
      decoration: InputDecoration(labelText: label),
    ),
  );

  @override
  Widget build(BuildContext context) {
    if (!hasSection(widget.api.user ?? {}, 'telegram_account')) {
      return const Text('Only owners can connect a Telegram account.');
    }
    final profile = status['profile'];
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        const Text(
          'Telegram account lookup',
          style: TextStyle(fontSize: 24, fontWeight: FontWeight.w700),
        ),
        const SizedBox(height: 12),
        const Text(
          'Connect your own Telegram user account to check saved customer phones, send tests, and enable automatic recharge receipts. Bot notifications are configured separately.',
        ),
        const SizedBox(height: 12),
        const Text(
          'AirLink encrypts the session and application credentials on this server. Login codes and two-step passwords are not saved. You can revoke this session in Telegram Settings → Devices.',
        ),
        const SizedBox(height: 16),
        if (busy) const LinearProgressIndicator(),
        if (cooldownNotice) cooldownMessage,
        if (error != null)
          Text(
            error!,
            style: TextStyle(color: Theme.of(context).colorScheme.error),
          ),
        if (stage == 'connected') ...[
          Text(
            'Connected: ${profile?['first_name'] ?? ''} ${profile?['last_name'] ?? ''}',
          ),
          if (profile?['username'] != null) Text('@${profile['username']}'),
          RechargeTelegramSettings(api: widget.api),
          const Text(
            'Open ISP card → customer details → Customer Telegram. AirLink checks that customer’s saved phone when you open the panel. Unknown means no accessible match; it does not prove the number has no Telegram account.',
          ),
        ] else if (stage == 'code') ...[
          const Text(
            'Enter the login code Telegram sent to your Telegram app or another method chosen by Telegram. This login attempt expires after 10 minutes.',
          ),
          field(code, 'Telegram login code', secret: true, numeric: true),
          FilledButton(
            onPressed:
                !canEditSection(widget.api.user ?? {}, 'telegram_account') ||
                    busy ||
                    coolingDown
                ? null
                : () => run(verify),
            child: const Text('Verify code'),
          ),
        ] else if (stage == 'password') ...[
          const Text('Your Telegram account uses two-step verification.'),
          field(password, 'Telegram two-step password', secret: true),
          FilledButton(
            onPressed:
                !canEditSection(widget.api.user ?? {}, 'telegram_account') ||
                    busy ||
                    coolingDown
                ? null
                : () => run(verify),
            child: const Text('Sign in to Telegram'),
          ),
        ] else ...[
          const SelectableText(
            'Get your own API ID and API hash at https://my.telegram.org → API development tools. These are different from the owner bot token.',
          ),
          const SizedBox(height: 12),
          field(apiId, 'Telegram API ID', numeric: true),
          field(apiHash, 'Telegram API hash', secret: true),
          field(phone, 'Your Telegram phone number (+country code)'),
          FilledButton(
            onPressed:
                !canEditSection(widget.api.user ?? {}, 'telegram_account') ||
                    busy ||
                    coolingDown
                ? null
                : () => run(login),
            child: const Text('Send login code'),
          ),
        ],
        if (stage != 'disconnected' || error != null)
          TextButton(
            onPressed:
                !canEditSection(widget.api.user ?? {}, 'telegram_account') ||
                    busy ||
                    coolingDown
                ? null
                : () => run(() async {
                    status = Map<String, dynamic>.from(
                      await widget.api.request(
                        telegramAccountPath,
                        method: 'DELETE',
                      ),
                    );
                    if (mounted) {
                      code.clear();
                      password.clear();
                      apiHash.clear();
                    }
                  }),
            child: Text(
              stage == 'connected'
                  ? 'Disconnect Telegram account'
                  : 'Cancel login',
            ),
          ),
      ],
    );
  }
}

class TelegramPhoneLookup extends StatefulWidget {
  const TelegramPhoneLookup({
    super.key,
    required this.api,
    required this.customerId,
    this.language = 'en',
  });
  final Api api;
  final int customerId;
  final String language;
  @override
  State<TelegramPhoneLookup> createState() => _TelegramPhoneLookupState();
}

class _TelegramPhoneLookupState extends State<TelegramPhoneLookup>
    with TelegramCooldown<TelegramPhoneLookup> {
  final recipientUsername = TextEditingController();
  bool busy = true, connected = false;
  String? error, message;
  Map<String, dynamic>? result, sender;

  @override
  void initState() {
    super.initState();
    check();
  }

  @override
  void dispose() {
    recipientUsername.dispose();
    super.dispose();
  }

  Future<void> selectUsername() async {
    if (busy ||
        coolingDown ||
        !connected ||
        !hasSection(widget.api.user ?? {}, 'telegram_account')) {
      return;
    }
    setState(() {
      busy = true;
      error = null;
      result = null;
      message = null;
      cooldownNotice = false;
    });
    try {
      final found = await widget.api.request(
        '$telegramAccountPath/users/${widget.customerId}/recipient',
        method: 'POST',
        body: {'username': recipientUsername.text.trim()},
      );
      if (mounted) result = Map<String, dynamic>.from(found);
    } catch (e) {
      if (mounted && !acceptCooldownError(e)) error = e.toString();
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> check() async {
    if (!hasSection(widget.api.user ?? {}, 'telegram_account') || coolingDown) {
      return;
    }
    setState(() {
      busy = true;
      error = null;
      result = null;
      message = null;
      cooldownNotice = false;
    });
    try {
      final account = await widget.api.request(telegramAccountPath);
      if (!mounted) return;
      connected = account['stage'] == 'connected';
      sender = account['profile'] == null
          ? null
          : Map<String, dynamic>.from(account['profile']);
      acceptCooldown(account['retry_after_seconds']);
      if (coolingDown) return;
      if (connected) {
        final found = await widget.api.request(
          '$telegramAccountPath/users/${widget.customerId}/lookup',
          method: 'POST',
        );
        if (mounted) result = Map<String, dynamic>.from(found);
      }
    } catch (e) {
      if (mounted && !acceptCooldownError(e)) error = e.toString();
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> sendTest() async {
    final token = result?['test_token'];
    if (busy || coolingDown || token == null) return;
    setState(() {
      busy = true;
      error = null;
      message = null;
      cooldownNotice = false;
      // Consume this intent locally before sending; only an acknowledged success
      // supplies another intent for a new, explicit click.
      result?.remove('test_token');
    });
    try {
      final response = await widget.api.request(
        '$telegramAccountPath/users/${widget.customerId}/test',
        method: 'POST',
        body: {'test_token': token, 'language': widget.language},
      );
      if (response['sent'] != true) {
        throw StateError(
          'Telegram did not confirm the test. Check the customer chat before trying again.',
        );
      }
      if (mounted) {
        message = 'Telegram accepted the test from your connected account.';
        if (response['next_test_token'] is String) {
          result?['test_token'] = response['next_test_token'];
        }
      }
    } catch (e) {
      if (mounted && !acceptCooldownError(e)) error = e.toString();
    } finally {
      if (mounted) {
        setState(() {
          busy = false;
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    if (!hasSection(widget.api.user ?? {}, 'telegram_account')) {
      return const SizedBox.shrink();
    }
    final person = result?['profile'];
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            const Text(
              'Telegram phone lookup',
              style: TextStyle(fontWeight: FontWeight.w700),
            ),
            if (busy) const LinearProgressIndicator(),
            if (cooldownNotice) cooldownMessage,
            if (error != null)
              Text(
                error!,
                style: TextStyle(color: Theme.of(context).colorScheme.error),
              ),
            if (message != null) Text(message!),
            if (!busy && !connected && error == null)
              const Text(
                'Connect your Telegram user account in My account → Telegram account lookup to check this saved customer phone.',
              ),
            if (result?['status'] == 'found') ...[
              const Text('Telegram account found'),
              if (result?['matched_by'] == 'username')
                const Text(
                  'Selected by username for this customer’s test. Check the name and Telegram ID below before sending.',
                ),
              Text(
                '${person?['first_name'] ?? ''} ${person?['last_name'] ?? ''}',
              ),
              if (person?['username'] != null) Text('@${person['username']}'),
              Text('Telegram ID: ${person?['id'] ?? ''}'),
            ],
            if (result?['status'] == 'unknown')
              Text(
                result?['matched_by'] == 'username'
                    ? 'No accessible user account found for this username. Enter a person’s Telegram @username.'
                    : 'Unknown — Telegram returned no accessible match. Privacy settings may prevent discovery. You can select the customer by Telegram username below.',
              ),
            if (result != null)
              const Text(
                'Phone tests and enabled automatic recharge receipts use the connected Telegram user account. The customer must still start and link the owner bot for bot notifications.',
              ),
            if (connected) ...[
              const SizedBox(height: 12),
              TextField(
                controller: recipientUsername,
                enabled: !busy && !coolingDown,
                autocorrect: false,
                decoration: const InputDecoration(
                  labelText: 'Customer Telegram @username (optional)',
                ),
                onChanged: (_) => setState(() {
                  result = null;
                  message = null;
                  error = null;
                }),
              ),
              OutlinedButton.icon(
                onPressed:
                    busy || coolingDown || recipientUsername.text.trim().isEmpty
                    ? null
                    : selectUsername,
                icon: const Icon(Icons.person_search_outlined),
                label: const Text('Find by username'),
              ),
              const SizedBox(height: 12),
              Text(
                sender?['username'] != null
                    ? 'Test sender: @${sender!['username']}'
                    : 'Test sender: ${sender?['first_name'] ?? 'connected Telegram account'} ${sender?['last_name'] ?? ''}',
              ),
              FilledButton.icon(
                onPressed:
                    !canEditSection(
                          widget.api.user ?? {},
                          'telegram_account',
                        ) ||
                        busy ||
                        coolingDown ||
                        result?['test_token'] == null
                    ? null
                    : sendTest,
                icon: const Icon(Icons.send_outlined),
                label: const Text('Send test from connected account'),
              ),
              const Text(
                'Each click sends one test in the selected notification language. You can send another after Telegram accepts it. Telegram cooldowns and privacy settings still apply. Check the recipient again if the selection is older than five minutes.',
              ),
            ],
            OutlinedButton.icon(
              onPressed:
                  !canEditSection(widget.api.user ?? {}, 'telegram_account') ||
                      busy ||
                      coolingDown
                  ? null
                  : check,
              icon: const Icon(Icons.search),
              label: const Text('Check saved phone'),
            ),
          ],
        ),
      ),
    );
  }
}
