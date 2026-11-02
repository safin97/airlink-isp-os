import 'app_language.dart';
import 'dart:async';
import 'dart:convert';
import 'package:flutter/material.dart';
import 'api.dart';
import 'section_access.dart';

class Sas4Recharge extends StatefulWidget {
  final Api api;
  final int userId;
  final bool hasUnsavedEdits;
  const Sas4Recharge({
    super.key,
    required this.api,
    required this.userId,
    this.hasUnsavedEdits = false,
  });
  @override
  State<Sas4Recharge> createState() => _Sas4RechargeState();
}

class _Sas4RechargeState extends State<Sas4Recharge> with LanguageRebuild {
  final pin = TextEditingController();
  final form = GlobalKey<FormState>();
  Map<String, dynamic>? info;
  final gateways = <String, dynamic>{};
  Map<String, dynamic>? order;
  List<dynamic> history = [];
  String method = 'credit';
  int? extensionId;
  bool loading = true;
  bool submitting = false;
  bool submitted = false;
  bool polling = false;
  String? error;
  Timer? timer;
  bool get bank => method == 'fib' || method == 'fastpay';
  Map get methods => info?['methods'] as Map? ?? {'card': true};
  bool get permitted => methods[bank ? 'credit' : method] == true;
  bool get ready =>
      canEditSection(widget.api.user ?? {}, 'isp_card') &&
      error == null &&
      permitted &&
      (!bank || gateways[method]?['configured'] == true) &&
      (method != 'extend' ||
          (extensionId != null && info?['extension']?['cost'] != null)) &&
      (method != 'credit' || info?['manager_cost'] != null) &&
      (!bank || info?['customer_price'] != null);

  @override
  void initState() {
    super.initState();
    load();
  }

  @override
  void dispose() {
    timer?.cancel();
    pin.dispose();
    super.dispose();
  }

  Future<void> load({int? selectedExtension}) async {
    setState(() {
      loading = true;
      error = null;
    });
    try {
      final suffix = selectedExtension == null
          ? ''
          : '?extension_id=$selectedExtension';
      final data = await widget.api.request(
        '/integrations/sas4/users/${widget.userId}/recharge$suffix',
      );
      if (!mounted) return;
      setState(() {
        final initial = info == null;
        info = Map<String, dynamic>.from(data);
        extensionId = info?['extension']?['id'];
        if (initial) {
          method = methods['credit'] == true
              ? 'credit'
              : methods['card'] == true
              ? 'card'
              : 'extend';
        }
      });
      if (selectedExtension == null) {
        try {
          final configs = await widget.api.request('/payments/gateways');
          final payments = await widget.api.request(
            '/payments/users/${widget.userId}',
          );
          if (!mounted) return;
          setState(() {
            if (configs is List) {
              for (final row in configs) {
                gateways[row['provider']] = row;
              }
            }
            history = payments is List ? payments : [];
            final pending = history
                .where(
                  (o) => [
                    'creating',
                    'pending',
                    'activating',
                    'paid_review',
                    'creation_unknown',
                  ].contains(o['status']),
                )
                .firstOrNull;
            if (pending != null) {
              order = Map<String, dynamic>.from(pending);
              submitted = true;
            }
          });
          if (order != null) startPolling();
        } catch (_) {
          /* Direct SAS4 recharge remains available if payment setup cannot load. */
        }
      }
    } catch (e) {
      if (mounted) setState(() => error = e.toString());
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }

  void startPolling() {
    timer?.cancel();
    if (order != null &&
        ['pending', 'creating', 'activating'].contains(order!['status'])) {
      timer = Timer.periodic(const Duration(seconds: 5), (_) => checkPayment());
    }
  }

  Future<void> checkPayment() async {
    if (polling || order == null) return;
    polling = true;
    try {
      final data = await widget.api.request('/payments/orders/${order!['id']}');
      if (!mounted) return;
      setState(() {
        order = Map<String, dynamic>.from(data);
        error = null;
      });
      if (order!['status'] == 'completed') {
        timer?.cancel();
        Navigator.pop(context, true);
      } else if (![
        'pending',
        'creating',
        'activating',
      ].contains(order!['status'])) {
        timer?.cancel();
      }
    } catch (e) {
      if (mounted) setState(() => error = e.toString());
    } finally {
      polling = false;
    }
  }

  Future<void> recharge() async {
    if (submitting || submitted || !ready || !form.currentState!.validate()) {
      return;
    }
    setState(() {
      submitting = true;
      submitted = true;
      error = null;
    });
    try {
      if (bank) {
        final data = await widget.api.request(
          '/payments/users/${widget.userId}',
          method: 'POST',
          retry: false,
          body: {
            'provider': method,
            'transaction_id': info!['transaction_id'],
            'expected_amount': info!['customer_price'],
            'expected_cost': info!['manager_cost'],
            'expected_profile_id': info!['profile_id'],
            'expected_expiration': info!['expiration'],
          },
        );
        if (!mounted) return;
        setState(() => order = Map<String, dynamic>.from(data));
        startPolling();
      } else {
        final data = <String, dynamic>{
          'method': method,
          'transaction_id': info!['transaction_id'],
        };
        if (method == 'card') {
          data['pin'] = pin.text.trim();
        } else {
          data.addAll({
            'expected_cost': method == 'extend'
                ? info!['extension']['cost']
                : info!['manager_cost'],
            'expected_profile_id': info!['profile_id'],
            'expected_expiration': info!['expiration'],
          });
          if (method == 'extend') data['extension_id'] = extensionId;
        }
        final result = await widget.api.request(
          '/integrations/sas4/users/${widget.userId}/recharge',
          method: 'POST',
          retry: false,
          body: data,
        );
        if (result['recharged'] != true) {
          throw Exception(
            'Recharge was not confirmed. Check this user before trying again.',
          );
        }
        pin.clear();
        if (mounted) {
          setState(() => submitting = false);
          Navigator.pop(context, true);
        }
      }
    } catch (e) {
      pin.clear();
      if (mounted) setState(() => error = e.toString());
    } finally {
      if (mounted) setState(() => submitting = false);
    }
  }

  Widget paymentView() {
    final checkout = order!['checkout'] as Map? ?? {};
    final status = order!['status'];
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: [
        Text(
          '${order!['provider'] == 'fib' ? 'FIB Bank' : 'FastPay'} • ${order!['amount']} ${order!['currency']}',
          style: const TextStyle(fontWeight: FontWeight.w600),
        ),
        if (order!['environment'] == 'sandbox')
          const AppText('Sandbox payment: no real service will be recharged.'),
        const SizedBox(height: 12),
        if (status == 'pending') ...[
          const AppText(
            'Scan with the banking app to pay. Payment is verified automatically before service is recharged.',
          ),
          const SizedBox(height: 12),
          if (checkout['qr_data'] is String)
            Center(
              child: Image.memory(
                base64Decode((checkout['qr_data'] as String).split(',').last),
                width: 240,
                height: 240,
                errorBuilder: (_, _, _) => const AppText(
                  'QR image unavailable. Use the payment code below.',
                ),
              ),
            ),
          if (checkout['qr_url'] is String)
            Center(
              child: Image.network(
                checkout['qr_url'],
                width: 240,
                height: 240,
                webHtmlElementStrategy: WebHtmlElementStrategy.fallback,
                errorBuilder: (_, _, _) => const AppText(
                  'QR image unavailable. Check merchant setup before retrying.',
                ),
              ),
            ),
          if (checkout['code'] != null)
            SelectableText('Payment code: ${checkout['code']}'),
        ],
        const SizedBox(height: 12),
        Text(switch (status) {
          'creating' => 'Creating payment…',
          'pending' => 'Waiting for payment…',
          'activating' => 'Payment verified. Recharging service…',
          'completed' => 'Payment verified and service recharged.',
          'sandbox_paid' =>
            'Test payment verified. No real service was recharged.',
          'declined' => 'Payment declined or expired.',
          _ =>
            order!['detail'] ??
                'Check the merchant portal before starting another payment.',
        }),
        if (order!['detail'] != null &&
            ['pending', 'activating'].contains(status))
          Text(order!['detail']),
        const SizedBox(height: 8),
        SelectableText(
          'Reference: ${order!['id']}',
          style: const TextStyle(fontSize: 12),
        ),
        const AppText(
          'You can close this window. Payment checks continue on the server.',
          style: TextStyle(fontSize: 12),
        ),
      ],
    );
  }

  Widget rechargeMethods() {
    final colors = Theme.of(context).colorScheme;
    return Wrap(
      spacing: 10,
      runSpacing: 10,
      children: [
        for (final type in const [
          ('credit', 'Manager balance', Icons.account_balance_wallet_outlined),
          ('fib', 'FIB Bank', Icons.account_balance_outlined),
          ('fastpay', 'FastPay', Icons.payments_outlined),
          ('extend', 'Extend service', Icons.more_time),
          ('card', 'Card PIN', Icons.credit_card_outlined),
        ])
          SizedBox(
            width: 104,
            height: 104,
            child: Semantics(
              selected: method == type.$1,
              child: Material(
                color: method == type.$1
                    ? colors.primaryContainer
                    : colors.surface,
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(12),
                  side: BorderSide(
                    color: method == type.$1
                        ? colors.primary
                        : colors.outlineVariant,
                    width: method == type.$1 ? 2 : 1,
                  ),
                ),
                clipBehavior: Clip.antiAlias,
                child: InkWell(
                  key: ValueKey('recharge-method-${type.$1}'),
                  onTap: loading || submitted
                      ? null
                      : () => setState(() {
                          method = type.$1;
                          error = null;
                        }),
                  child: Padding(
                    padding: const EdgeInsets.all(10),
                    child: Column(
                      mainAxisAlignment: MainAxisAlignment.center,
                      children: [
                        Icon(
                          type.$3,
                          size: 28,
                          color: method == type.$1
                              ? colors.onPrimaryContainer
                              : colors.onSurfaceVariant,
                        ),
                        const SizedBox(height: 8),
                        Flexible(
                          child: AppText(
                            type.$2,
                            textAlign: TextAlign.center,
                            maxLines: 3,
                            overflow: TextOverflow.ellipsis,
                            style: TextStyle(
                              fontSize: 12,
                              fontWeight: FontWeight.w600,
                              color: method == type.$1
                                  ? colors.onPrimaryContainer
                                  : colors.onSurface,
                            ),
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
              ),
            ),
          ),
      ],
    );
  }

  @override
  Widget build(BuildContext context) => PopScope(
    canPop: !submitting,
    child: AlertDialog(
      title: const AppText('Recharge card'),
      content: SizedBox(
        width: 460,
        child: SingleChildScrollView(
          child: Form(
            key: form,
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                if (loading) const LinearProgressIndicator(),
                if (info != null) ...[
                  Text(
                    'User: ${info!['username']}',
                    style: const TextStyle(fontWeight: FontWeight.w600),
                  ),
                  const SizedBox(height: 8),
                  Text('Profile: ${info!['profile'] ?? '—'}'),
                  Text('Current expiry: ${info!['expiration'] ?? '—'}'),
                  if (widget.hasUnsavedEdits) ...[
                    const SizedBox(height: 12),
                    const AppText(
                      'Your edits will stay unsaved. Recharge uses the current SAS4 profile and expiry shown above.',
                    ),
                  ],
                  const SizedBox(height: 20),
                  if (order != null)
                    paymentView()
                  else ...[
                    rechargeMethods(),
                    const SizedBox(height: 16),
                    if (!permitted)
                      const AppText(
                        'Your SAS4 account does not have permission for this method.',
                      ),
                    if (bank && gateways[method]?['configured'] != true)
                      const AppText(
                        'Set up this merchant account in My account → Payment setup to enable automatic payments.',
                      ),
                    if (bank && gateways[method]?['configured'] == true) ...[
                      Text(
                        'Customer payment: ${info!['customer_price'] ?? 'Unavailable'} ${info!['currency'] ?? ''}',
                      ),
                      Text(
                        'SAS4 manager cost: ${info!['manager_cost'] ?? 'Unavailable'} ${info!['currency'] ?? ''}',
                      ),
                      Text(
                        gateways[method]['environment'] == 'sandbox'
                            ? 'Sandbox: test payment only; no real service activation.'
                            : 'Production: payment will be collected, then service recharged from your SAS4 manager balance.',
                      ),
                    ],
                    if (method == 'credit') ...[
                      Text(
                        'Manager balance: ${info!['manager_balance'] ?? '—'}',
                      ),
                      Text(
                        'Recharge cost: ${info!['manager_cost'] ?? 'Unavailable'} ${info!['currency'] ?? ''}',
                        style: const TextStyle(fontWeight: FontWeight.w600),
                      ),
                      const AppText(
                        'One activation will be charged to your SAS4 manager balance.',
                      ),
                    ],
                    if (method == 'extend') ...[
                      DropdownButtonFormField<int>(
                        key: ValueKey(extensionId),
                        initialValue: extensionId,
                        isExpanded: true,
                        decoration: InputDecoration(
                          labelText: tr('Select extension'),
                          border: OutlineInputBorder(),
                        ),
                        items: [
                          for (final item
                              in (info!['extensions'] as List? ?? []))
                            DropdownMenuItem(
                              value: item['id'] as int,
                              child: Text('${item['name']}'),
                            ),
                        ],
                        onChanged: loading || submitted
                            ? null
                            : (value) {
                                if (value != null) {
                                  load(selectedExtension: value);
                                }
                              },
                      ),
                      const SizedBox(height: 12),
                      if (extensionId == null)
                        const AppText(
                          'Test is not available for this profile. Select an allowed extension.',
                        ),
                      Text(
                        'Extension cost: ${info?['extension']?['cost'] ?? 'Unavailable'} ${info!['currency'] ?? ''}',
                      ),
                      const AppText(
                        'Extension is charged to your SAS4 manager balance.',
                      ),
                      if (info!['warning'] != null) Text(info!['warning']),
                    ],
                    if (method == 'card')
                      TextFormField(
                        controller: pin,
                        enabled: !submitted,
                        obscureText: true,
                        autocorrect: false,
                        enableSuggestions: false,
                        maxLength: 128,
                        decoration: InputDecoration(
                          labelText: tr('Card PIN'),
                          counterText: '',
                          border: OutlineInputBorder(),
                        ),
                        validator: (value) =>
                            value == null || value.trim().isEmpty
                            ? 'Enter the card PIN'
                            : null,
                      ),
                    if (history.isNotEmpty) ...[
                      const Divider(height: 28),
                      const AppText('Recent payments'),
                      for (final payment in history.take(3))
                        ListTile(
                          contentPadding: EdgeInsets.zero,
                          dense: true,
                          title: Text(
                            '${payment['provider'] == 'fib' ? 'FIB Bank' : 'FastPay'} • ${payment['amount']} ${payment['currency']}',
                          ),
                          subtitle: Text('${payment['status']}'),
                          onTap: () {
                            setState(() {
                              order = Map<String, dynamic>.from(payment);
                              submitted = true;
                            });
                            startPolling();
                          },
                        ),
                    ],
                  ],
                ],
                if (error != null)
                  Padding(
                    padding: const EdgeInsets.only(top: 16),
                    child: Text(
                      error!,
                      style: TextStyle(
                        color: Theme.of(context).colorScheme.error,
                      ),
                    ),
                  ),
              ],
            ),
          ),
        ),
      ),
      actions: [
        TextButton(
          onPressed: submitting ? null : () => Navigator.pop(context, false),
          child: const AppText('Close'),
        ),
        if (order == null)
          FilledButton.icon(
            onPressed: loading || submitted || info == null || !ready
                ? null
                : recharge,
            icon: const Icon(Icons.credit_card),
            label: Text(
              submitting
                  ? 'Submitting…'
                  : bank
                  ? 'Create payment'
                  : method == 'extend'
                  ? 'Extend service'
                  : 'Recharge card',
            ),
          ),
      ],
    ),
  );
}
