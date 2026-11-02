import 'package:flutter/material.dart';
import 'api.dart';

class PaymentSettings extends StatefulWidget {
  final Api api;
  const PaymentSettings({super.key, required this.api});
  @override
  State<PaymentSettings> createState() => _PaymentSettingsState();
}

class _PaymentSettingsState extends State<PaymentSettings> {
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
  void dispose() {
    for (final c in [...merchants.values, ...secrets.values]) {
      c.dispose();
    }
    super.dispose();
  }

  Future<void> load() async {
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
  Widget build(BuildContext context) => ExpansionTile(
    tilePadding: EdgeInsets.zero,
    title: const Text('Payment setup'),
    subtitle: const Text('FIB Bank and FastPay merchant API accounts'),
    onExpansionChanged: (open) {
      if (open) load();
    },
    children: [
      const Text(
        'Use merchant API credentials, not your personal banking login. Secrets are stored encrypted and never shown again.',
      ),
      if (busy) const LinearProgressIndicator(),
      if (message != null)
        Padding(
          padding: const EdgeInsets.symmetric(vertical: 12),
          child: Text(message!),
        ),
      if (!loaded && !busy)
        TextButton(onPressed: load, child: const Text('Load payment settings')),
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
                const SizedBox(height: 12),
                DropdownButtonFormField<String>(
                  initialValue: environments[provider],
                  decoration: const InputDecoration(labelText: 'Environment'),
                  items: const [
                    DropdownMenuItem(
                      value: 'sandbox',
                      child: Text('Sandbox — test payments'),
                    ),
                    DropdownMenuItem(
                      value: 'production',
                      child: Text('Production — real payments'),
                    ),
                  ],
                  onChanged: busy
                      ? null
                      : (value) =>
                            setState(() => environments[provider] = value!),
                ),
                const SizedBox(height: 12),
                TextFormField(
                  controller: merchants[provider],
                  enabled: !busy,
                  decoration: InputDecoration(
                    labelText: provider == 'fib'
                        ? 'FIB client ID'
                        : 'FastPay store ID',
                  ),
                ),
                const SizedBox(height: 12),
                TextFormField(
                  controller: secrets[provider],
                  enabled: !busy,
                  obscureText: true,
                  autocorrect: false,
                  enableSuggestions: false,
                  decoration: InputDecoration(
                    labelText: provider == 'fib'
                        ? 'FIB client secret'
                        : 'FastPay store password',
                    helperText: configured[provider] == true
                        ? 'Leave blank to keep the saved secret'
                        : 'Provided by your merchant payment provider',
                  ),
                ),
                const SizedBox(height: 12),
                const Text(
                  'Sandbox payments never recharge a real SAS4 account. Production payments recharge only after server verification.',
                  style: TextStyle(fontSize: 12),
                ),
                const SizedBox(height: 12),
                FilledButton(
                  onPressed: busy ? null : () => save(provider),
                  child: const Text('Save merchant settings'),
                ),
              ],
            ),
          ),
    ],
  );
}
