import 'section_access.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'api.dart';
import 'telegram_account.dart';

class CustomerTelegram extends StatefulWidget {
  const CustomerTelegram({
    super.key,
    required this.api,
    this.customerId,
    this.embedded = false,
  });
  final Api api;
  final int? customerId;
  final bool embedded;
  @override
  State<CustomerTelegram> createState() => _CustomerTelegramState();
}

class _CustomerTelegramState extends State<CustomerTelegram> {
  static const path = '/integrations/customer-telegram';
  final token = TextEditingController();
  final timezone = TextEditingController(text: 'Asia/Baghdad');
  Map<String, dynamic>? bot, customer;
  String language = 'en';
  String? error, link, message;
  bool busy = true, enabled = true;
  bool get canManageBot =>
      canEditSection(widget.api.user ?? {}, 'telegram_bot') &&
      bot?['can_manage'] != false;
  String get customerPath => '$path/users/${widget.customerId}';
  bool get testReady =>
      (customer?['test_ready'] ?? customer?['linked']) == true;

  @override
  void initState() {
    super.initState();
    run(load);
  }

  @override
  void dispose() {
    token.dispose();
    timezone.dispose();
    super.dispose();
  }

  Future<void> load() async {
    final settings = Map<String, dynamic>.from(await widget.api.request(path));
    final status = widget.customerId == null
        ? null
        : Map<String, dynamic>.from(await widget.api.request(customerPath));
    if (!mounted) return;
    setState(() {
      bot = settings;
      customer = status;
      enabled = settings['configured'] != true || settings['enabled'] == true;
      timezone.text = settings['timezone'] ?? 'Asia/Baghdad';
      language = status?['language'] ?? 'en';
    });
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
      if (mounted) setState(() => error = e.toString());
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> saveBot() async {
    await widget.api.request(
      path,
      method: 'PUT',
      body: {
        'enabled': enabled,
        'timezone': timezone.text.trim(),
        if (token.text.trim().isNotEmpty) 'bot_token': token.text.trim(),
      },
    );
    if (!mounted) return;
    token.clear();
    link = null;
    await load();
    if (mounted) setState(() => message = 'Customer bot saved.');
  }

  Future<void> createLink() async {
    final result = await widget.api.request(
      '$customerPath/link',
      method: 'POST',
      body: {'language': language},
    );
    await load();
    if (mounted) setState(() => link = result['url']);
  }

  Future<void> sendTest() async {
    final result = await widget.api.request(
      '$customerPath/test',
      method: 'POST',
    );
    if (result is! Map || result['sent'] != true) {
      throw StateError(
        'Telegram did not confirm the test. Refresh delivery status.',
      );
    }
    try {
      await load();
    } catch (_) {
      // Delivery was confirmed even if refreshing status is temporarily unavailable.
    }
    if (mounted) {
      setState(
        () => message =
            'Test notification sent to the customer’s Telegram from the owner bot.',
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    final content = Center(
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 720),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            const Text(
              'Activation and expiry notifications',
              style: TextStyle(fontSize: 24, fontWeight: FontWeight.w700),
            ),
            const SizedBox(height: 12),
            const Text(
              'Linked customers receive a message after a confirmed card PIN, balance, FIB, FastPay or service-extension activation in AirLink, plus one reminder three days before service expiry.',
            ),
            const SizedBox(height: 16),
            if (busy) const LinearProgressIndicator(),
            if (error != null)
              Text(
                error!,
                style: TextStyle(color: Theme.of(context).colorScheme.error),
              ),
            if (message != null) Text(message!),
            if (widget.customerId == null) ...[
              const Text(
                'Save the shared owner bot token here. All linked customers receive notifications from this bot, including activations by managers. To link customers, open ISP card → customer details → Customer Telegram. Configure the owner SAS4 connection in ISP card before saving the bot.',
              ),
              const SizedBox(height: 12),
              OutlinedButton.icon(
                onPressed: busy ? null : () => run(load),
                icon: const Icon(Icons.refresh),
                label: const Text('Refresh bot status'),
              ),
            ],
            if (bot != null) ...[
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(20),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.stretch,
                    children: [
                      const Text(
                        'Owner bot for customer notifications',
                        style: TextStyle(fontWeight: FontWeight.w700),
                      ),
                      const SizedBox(height: 8),
                      if (bot!['username'] != null)
                        Text('@${bot!['username']}'),
                      Text(
                        bot!['enabled'] == true
                            ? 'Owner bot enabled'
                            : 'Owner bot not enabled',
                      ),
                      if (canManageBot) ...[
                        const Text(
                          'Create a dedicated bot with @BotFather. Use a different bot from device alerts or other apps. Changing the owner bot requires customers to link again.',
                        ),
                        const SizedBox(height: 12),
                        TextField(
                          controller: token,
                          obscureText: true,
                          enableSuggestions: false,
                          autocorrect: false,
                          decoration: InputDecoration(
                            labelText: bot!['configured'] == true
                                ? 'New bot token (leave blank to keep)'
                                : 'Bot token',
                          ),
                        ),
                        const SizedBox(height: 12),
                        TextField(
                          controller: timezone,
                          decoration: const InputDecoration(
                            labelText: 'SAS4 expiry timezone',
                            helperText: 'Example: Asia/Baghdad',
                          ),
                        ),
                        SwitchListTile(
                          contentPadding: EdgeInsets.zero,
                          title: const Text('Enable customer notifications'),
                          value: enabled,
                          onChanged: busy
                              ? null
                              : (value) => setState(() => enabled = value),
                        ),
                        if (bot!['last_error'] != null)
                          Text(bot!['last_error']),
                        FilledButton(
                          onPressed: busy ? null : () => run(saveBot),
                          child: const Text('Save customer bot'),
                        ),
                      ] else ...[
                        const SizedBox(height: 12),
                        const Text(
                          'Customer notifications use the owner’s Telegram bot. Only an owner can configure its token in My account → Telegram bot token. You can link customers you can access in ISP card.',
                        ),
                      ],
                    ],
                  ),
                ),
              ),
              if (widget.customerId != null) ...[
                if (customer?['phone_recharges_enabled'] == true)
                  const Card(
                    child: Padding(
                      padding: EdgeInsets.all(16),
                      child: Text(
                        'Automatic recharge receipts are enabled. After a successful recharge, the selected owner Telegram account sends the receipt using this customer’s saved phone. The bot link below is used for separate bot notifications.',
                      ),
                    ),
                  ),
                if ((customer?['account_recharges'] as List? ?? []).isNotEmpty)
                  Card(
                    child: Column(
                      children: [
                        const ListTile(
                          title: Text('Notifications from owner account'),
                        ),
                        for (final event in customer!['account_recharges'])
                          ListTile(
                            title: Text(
                              '${event['kind']} · ${event['status']}',
                            ),
                            subtitle: Text(
                              '${event['detail'] ?? ''}\n${event['created_at']}',
                            ),
                          ),
                      ],
                    ),
                  ),
                if (hasSection(widget.api.user ?? {}, 'telegram_account'))
                  TelegramPhoneLookup(
                    key: ValueKey(widget.customerId),
                    api: widget.api,
                    customerId: widget.customerId!,
                    language: language,
                  ),
                const SizedBox(height: 16),
                Card(
                  child: Padding(
                    padding: const EdgeInsets.all(20),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        Text(
                          customer?['linked'] == true
                              ? 'Customer linked'
                              : customer?['telegram_linked'] == true
                              ? 'Telegram linked · phone verification pending'
                              : customer?['awaiting_phone'] == true
                              ? 'Waiting for customer to share their phone in Telegram'
                              : customer?['pending_link'] == true
                              ? 'Waiting for customer to start the bot'
                              : 'Customer not linked',
                          style: const TextStyle(fontWeight: FontWeight.w700),
                        ),
                        const SizedBox(height: 8),
                        Text(
                          customer?['phone_verified'] == true
                              ? 'Telegram phone matches the ISP card phone.'
                              : testReady
                              ? 'You can send a test to the existing Telegram chat. Phone verification is still required for automatic activation and expiry notifications.'
                              : customer?['phone_available'] == false
                              ? 'Save the customer phone in ISP card first. Use international format (+964…) or an Iraqi 07… mobile number.'
                              : 'The customer must tap Start, then Share my phone number in Telegram. AirLink checks that it matches the ISP card phone.',
                        ),
                        const SizedBox(height: 12),
                        DropdownButtonFormField<String>(
                          initialValue: language,
                          key: ValueKey(language),
                          decoration: const InputDecoration(
                            labelText: 'Notification language',
                          ),
                          items: const [
                            DropdownMenuItem(
                              value: 'en',
                              child: Text('English'),
                            ),
                            DropdownMenuItem(
                              value: 'ku',
                              child: Text('کوردی (بادینی)'),
                            ),
                            DropdownMenuItem(
                              value: 'ar',
                              child: Text('العربية'),
                            ),
                          ],
                          onChanged:
                              busy || customer?['language_managed'] == true
                              ? null
                              : (value) => setState(() => language = value!),
                        ),
                        if (customer?['language_managed'] == true)
                          const Text(
                            'Set for all ISP card customers in My account → Telegram account lookup.',
                          ),
                        const SizedBox(height: 12),
                        if (customer?['linked'] == true) ...[
                          if (customer?['language_managed'] != true)
                            OutlinedButton(
                              onPressed: busy
                                  ? null
                                  : () => run(() async {
                                      await widget.api.request(
                                        '$customerPath/language',
                                        method: 'PUT',
                                        body: {'language': language},
                                      );
                                      await load();
                                      if (mounted) {
                                        setState(
                                          () => message =
                                              'Customer language saved.',
                                        );
                                      }
                                    }),
                              child: const Text('Save language'),
                            ),
                          TextButton(
                            onPressed: busy
                                ? null
                                : () => run(() async {
                                    await widget.api.request(
                                      customerPath,
                                      method: 'DELETE',
                                    );
                                    link = null;
                                    await load();
                                  }),
                            child: const Text('Unlink customer'),
                          ),
                        ] else ...[
                          const Text(
                            'Give this private link only to this customer. It expires after 24 hours and works once. The customer must open Telegram, tap Start, and share their own phone number using the bot button. Creating a new link replaces the previous one.',
                          ),
                          const SizedBox(height: 12),
                          FilledButton.icon(
                            onPressed:
                                busy ||
                                    bot!['enabled'] != true ||
                                    customer?['phone_available'] == false
                                ? null
                                : () => run(createLink),
                            icon: const Icon(Icons.link),
                            label: const Text('Create customer link'),
                          ),
                          if (link != null) ...[
                            const SizedBox(height: 12),
                            SelectableText(link!),
                            OutlinedButton.icon(
                              onPressed: () async {
                                await Clipboard.setData(
                                  ClipboardData(text: link!),
                                );
                                if (mounted) {
                                  setState(
                                    () => message =
                                        'Private link copied. Share it only with this customer.',
                                  );
                                }
                              },
                              icon: const Icon(Icons.copy),
                              label: const Text('Copy private link'),
                            ),
                          ],
                        ],
                        const Text(
                          'The customer can send /stop to the owner bot to unsubscribe from automatic notifications. Phone lookup and account tests use the owner’s separate Telegram user account.',
                        ),
                        if (customer?['last_sent_at'] != null)
                          Text('Last sent: ${customer!['last_sent_at']}'),
                        if (customer?['last_error'] != null)
                          Text(customer!['last_error']),
                        const SizedBox(height: 12),
                        FilledButton.icon(
                          onPressed:
                              busy || !testReady || bot?['enabled'] != true
                              ? null
                              : () => run(sendTest),
                          icon: const Icon(Icons.send_outlined),
                          label: const Text('Send test to Telegram'),
                        ),
                        Text(
                          testReady
                              ? 'Uses the customer’s saved notification language. Wait 30 seconds between tests.'
                              : 'Complete the customer link, or verify again if their saved phone changed, before sending a test.',
                        ),
                        const SizedBox(height: 12),
                        OutlinedButton.icon(
                          onPressed: busy ? null : () => run(load),
                          icon: const Icon(Icons.refresh),
                          label: const Text('Refresh link and delivery status'),
                        ),
                        for (final event in customer?['recent'] ?? [])
                          ListTile(
                            contentPadding: EdgeInsets.zero,
                            title: Text(
                              '${event['kind']} · ${event['status']}',
                            ),
                            subtitle: Text('${event['created_at']}'),
                          ),
                      ],
                    ),
                  ),
                ),
              ],
            ],
          ],
        ),
      ),
    );
    return widget.embedded
        ? content
        : Scaffold(
            appBar: AppBar(title: const Text('Customer Telegram')),
            body: SingleChildScrollView(
              padding: const EdgeInsets.all(24),
              child: content,
            ),
          );
  }
}
