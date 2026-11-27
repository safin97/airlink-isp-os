import 'section_access.dart';
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
  bool get canView => hasSection(widget.api.user ?? {}, 'payment_gateways');
  bool get canEdit => canEditSection(widget.api.user ?? {}, 'payment_gateways');
  final merchants = {
    for (final p in ['fib', 'fastpay']) p: TextEditingController(),
  };
  final secrets = {
    for (final p in ['fib', 'fastpay']) p: TextEditingController(),
  };
  final environments = {'fib': 'sandbox', 'fastpay': 'sandbox'};
  final configured = <String, bool>{};
  final accessModes = {'fib': 'selected', 'fastpay': 'selected'};
  final managerIds = {
    for (final p in ['fib', 'fastpay']) p: <String>{},
  };
  List<dynamic> managers = [];
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
    if (!canView) return;
    if (loaded || busy) return;
    setState(() => busy = true);
    try {
      final results = await Future.wait([
        widget.api.request('/payments/gateways'),
        widget.api.request('/payments/gateways/managers'),
      ]);
      final rows = results[0];
      if (!mounted) return;
      setState(() {
        managers = List<dynamic>.from(results[1]);
        for (final row in rows) {
          final p = row['provider'];
          if (!merchants.containsKey(p)) continue;
          merchants[p]!.text = row['merchant_id'] ?? '';
          environments[p] = row['environment'] ?? 'sandbox';
          configured[p] = row['configured'] == true;
          accessModes[p] = row['access_mode'] ?? 'all';
          managerIds[p] = Set<String>.from(row['manager_ids'] ?? []);
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
          'access_mode': accessModes[provider],
          'manager_ids': accessModes[provider] == 'selected'
              ? managerIds[provider]!.toList()
              : <String>[],
        },
      );
      if (!mounted) return;
      secrets[provider]!.clear();
      setState(() {
        configured[provider] = true;
        message =
            'Merchant settings and manager access saved. Reopen Recharge card to use them.';
      });
    } catch (e) {
      if (mounted) setState(() => message = e.toString());
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> testFib() async {
    if (!canEdit || busy) return;
    setState(() {
      busy = true;
      message = null;
    });
    try {
      final result = await widget.api.request(
        '/payments/gateways/fib/test',
        method: 'POST',
        retry: false,
      );
      if (mounted) {
        setState(
          () => message = '${result['environment']}: ${result['detail']}',
        );
      }
    } catch (e) {
      if (mounted) setState(() => message = e.toString());
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => !canView
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
      'Configure FIB Bank and FastPay, then choose which AirLink managers may use each account. Managers use their own recharge permissions and do not need bank credentials.',
    ),
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
              DropdownButtonFormField<String>(
                key: ValueKey('payment-access-$provider'),
                initialValue: accessModes[provider],
                decoration: const InputDecoration(
                  labelText: 'Who can use this payment account?',
                ),
                items: const [
                  DropdownMenuItem(
                    value: 'all',
                    child: Text('All authorized users'),
                  ),
                  DropdownMenuItem(
                    value: 'selected',
                    child: Text('Selected managers'),
                  ),
                ],
                onChanged: busy || !canEdit
                    ? null
                    : (value) => setState(() => accessModes[provider] = value!),
              ),
              if (accessModes[provider] == 'selected') ...[
                if (managers.isEmpty)
                  const Text('No manager accounts available.'),
                for (final manager in managers)
                  CheckboxListTile(
                    key: ValueKey('payment-manager-$provider-${manager['id']}'),
                    title: Text(manager['username'].toString()),
                    subtitle: manager['active'] == false
                        ? const Text('Account disabled')
                        : null,
                    value: managerIds[provider]!.contains(manager['id']),
                    controlAffinity: ListTileControlAffinity.leading,
                    contentPadding: EdgeInsets.zero,
                    onChanged: busy || !canEdit
                        ? null
                        : (checked) => setState(() {
                            if (checked == true) {
                              managerIds[provider]!.add(
                                manager['id'].toString(),
                              );
                            } else {
                              managerIds[provider]!.remove(manager['id']);
                            }
                          }),
                  ),
                const Text('No managers selected means owners only.'),
              ],
              const Text(
                'Owners retain access. Changes apply to new payments; existing payments continue verification.',
              ),
              const SizedBox(height: 12),
              const AppText(
                'Sandbox payments never recharge a real SAS4 account. Production payments recharge only after server verification.',
                style: TextStyle(fontSize: 12),
              ),
              const SizedBox(height: 12),
              FilledButton(
                key: ValueKey('save-payment-$provider'),
                onPressed: busy || !canEdit ? null : () => save(provider),
                child: const AppText('Save merchant settings'),
              ),
              if (provider == 'fib') ...[
                TextButton.icon(
                  onPressed: !canEdit || busy || configured[provider] != true
                      ? null
                      : testFib,
                  icon: const Icon(Icons.network_check),
                  label: const AppText('Test saved FIB connection'),
                ),
                const AppText(
                  'Save changes first. This test checks your FIB credentials without creating a payment.',
                ),
              ],
            ],
          ),
        ),
  ];
}
