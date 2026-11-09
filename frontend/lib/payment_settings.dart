import 'app_language.dart';

import 'package:flutter/material.dart';

import 'api.dart';

class PaymentSettings extends StatefulWidget {
  final Api api;
  final bool initiallyExpanded;
  final bool embedded;
  const PaymentSettings({
    super.key,
    required this.api,
    this.initiallyExpanded = false,
    this.embedded = false,
  });
  @override
  State<PaymentSettings> createState() => _PaymentSettingsState();
}

class _PaymentSettingsState extends State<PaymentSettings>
    with LanguageRebuild {
  bool get canEdit => widget.api.user?['role'] == 'owner';
  final merchants = {
    for (final p in ['fib', 'fastpay']) p: TextEditingController(),
  };
  final secrets = {
    for (final p in ['fib', 'fastpay']) p: TextEditingController(),
  };
  final environments = {'fib': 'sandbox', 'fastpay': 'sandbox'};
  final configured = <String, bool>{};
  bool loaded = false;
  bool busy = false;
  String? message;
  @override
  void initState() {
    super.initState();
    if (widget.initiallyExpanded || widget.embedded) load();
  }

  @override
  void dispose() {
    for (final c in [...merchants.values, ...secrets.values]) {
      c.dispose();
    }
    super.dispose();
  }

  Future<void> load() async {
    if (!canEdit) return;
    if (loaded || busy) return;
    setState(() => busy = true);
    try {
      final rows = await widget.api.request('/payments/gateways');
      if (!mounted) return;
      setState(() {
        for (final row in rows) {
          final p = row['provider'];
          if (!merchants.containsKey(p)) continue;
          merchants[p]!.text = row['merchant_id'] ?? '';
          environments[p] = row['environment'] ?? 'sandbox';
          configured[p] = row['configured'] == true;
        }
        loaded = true;
      });
    } catch (e) {
      if (mounted) setState(() => message = e.toString());
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> save(String provider) async {
    if (!canEdit) return;
    setState(() {
      busy = true;
      message = null;
    });
    try {
      await widget.api.request(
        '/payments/gateways/$provider',
        method: 'PUT',
        body: {
          'merchant_id': merchants[provider]!.text.trim(),
          'secret': secrets[provider]!.text.isEmpty
              ? null
              : secrets[provider]!.text,
          'environment': environments[provider],
        },
      );
      if (!mounted) return;
      secrets[provider]!.clear();
      setState(() {
        configured[provider] = true;
        message = 'Merchant settings saved. Reopen Recharge card to use them.';
      });
    } catch (e) {
      if (mounted) setState(() => message = e.toString());
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => !canEdit
      ? const SizedBox.shrink()
      : widget.embedded
      ? Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: settingsContent(),
        )
      : ExpansionTile(
          initiallyExpanded: widget.initiallyExpanded,
          tilePadding: EdgeInsets.zero,
          title: const AppText('Payment setup'),
          subtitle: const AppText('FIB Bank and FastPay merchant API accounts'),
          onExpansionChanged: (open) {
            if (open) load();
          },
          children: settingsContent(),
        );

  List<Widget> settingsContent() => [
    const AppText(
      'Use merchant API credentials, not your personal banking login. Secrets are stored encrypted and never shown again.',
    ),
    if (busy) const LinearProgressIndicator(),
    if (message != null)
      Padding(
        padding: const EdgeInsets.symmetric(vertical: 12),
        child: Text(message!),
      ),
    if (!loaded && !busy)
      TextButton(
        onPressed: load,
        child: const AppText('Load payment settings'),
      ),
    if (loaded)
      for (final provider in ['fib', 'fastpay'])
        Padding(
          padding: const EdgeInsets.symmetric(vertical: 20),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Text(
                provider == 'fib' ? 'FIB Bank' : 'FastPay',
                style: const TextStyle(
                  fontSize: 18,
                  fontWeight: FontWeight.w600,
                ),
              ),
              AppText(
                configured[provider] == true ? 'Configured' : 'Not configured',
              ),
              const SizedBox(height: 12),
              DropdownButtonFormField<String>(
                initialValue: environments[provider],
                decoration: InputDecoration(labelText: tr('Environment')),
                items: const [
                  DropdownMenuItem(
                    value: 'sandbox',
                    child: AppText('Sandbox — test payments'),
                  ),
                  DropdownMenuItem(
                    value: 'production',
                    child: AppText('Production — real payments'),
                  ),
                ],
                onChanged: busy || !canEdit
                    ? null
                    : (value) =>
                          setState(() => environments[provider] = value!),
              ),
              const SizedBox(height: 12),
              TextFormField(
                controller: merchants[provider],
                enabled: !busy && canEdit,
                decoration: InputDecoration(
                  labelText: tr(
                    provider == 'fib' ? 'FIB client ID' : 'FastPay store ID',
                  ),
                ),
              ),
              const SizedBox(height: 12),
              TextFormField(
                controller: secrets[provider],
                enabled: !busy && canEdit,
                obscureText: true,
                autocorrect: false,
                enableSuggestions: false,
                decoration: InputDecoration(
                  labelText: tr(
                    provider == 'fib'
                        ? 'FIB client secret'
                        : 'FastPay store password',
                  ),
                  helperText: configured[provider] == true
                      ? 'Leave blank to keep the saved secret'
                      : 'Provided by your merchant payment provider',
                ),
              ),
              const SizedBox(height: 12),
              const AppText(
                'Sandbox payments never recharge a real SAS4 account. Production payments recharge only after server verification.',
                style: TextStyle(fontSize: 12),
              ),
              const SizedBox(height: 12),
              FilledButton(
                onPressed: busy || !canEdit ? null : () => save(provider),
                child: const AppText('Save merchant settings'),
              ),
            ],
          ),
        ),
  ];
}
