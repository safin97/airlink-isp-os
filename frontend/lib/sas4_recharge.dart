import 'app_language.dart';
import 'dart:async';
import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'api.dart';
import 'section_access.dart';
import 'payment_settings.dart';
import 'package:url_launcher/link.dart';

class Sas4Recharge extends StatefulWidget {
  final Api api;
  final int userId;
  final bool hasUnsavedEdits;
  final DateTime Function()? currentTime;
  const Sas4Recharge({
    super.key,
    required this.api,
    required this.userId,
    this.hasUnsavedEdits = false,
    this.currentTime,
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
  List<dynamic> savedCards = [];
  String? selectedCard;
  String? issuedPin;
  String? cardsError;
  bool cardsLoading = false;
  String method = 'credit';
  int? extensionId;
  bool loading = true;
  bool submitting = false;
  bool submitted = false;
  bool polling = false;
  bool showPin = false;
  String? error;
  String? connectionMessage;
  Timer? timer;
  Timer? countdown;
  DateTime? get paymentDeadline => order?['provider'] == 'fib'
      ? DateTime.tryParse(
          order?['expires_at'] ?? order?['checkout']?['valid_until'] ?? '',
        )
      : null;
  int? get paymentSecondsLeft {
    final deadline = paymentDeadline;
    if (deadline == null) return null;
    return (deadline
                .difference(widget.currentTime?.call() ?? DateTime.now())
                .inMilliseconds /
            1000)
        .ceil()
        .clamp(0, 300);
  }

  bool get paymentWindowEnded => paymentSecondsLeft == 0;
  Map? get selectedCardData =>
      savedCards.where((card) => card['id'] == selectedCard).firstOrNull
          as Map?;
  bool get bank => method == 'fib' || method == 'fastpay';
  Map get methods => info?['methods'] as Map? ?? {'card': true};
  bool get permitted =>
      methods[method == 'fib'
              ? 'card'
              : bank
              ? 'credit'
              : method] ==
          true &&
      (method != 'fib' || widget.api.user?['role'] == 'owner');
  bool get ready =>
      canEditSection(widget.api.user ?? {}, 'isp_card') &&
      error == null &&
      permitted &&
      (!bank || gateways[method]?['configured'] == true) &&
      (method != 'fib' ||
          (selectedCardData?['price_iqd'] != null && !cardsLoading)) &&
      (method != 'extend' ||
          (extensionId != null && info?['extension']?['cost'] != null)) &&
      (method != 'credit' || info?['manager_cost'] != null) &&
      (method != 'fastpay' || info?['customer_price'] != null);

  @override
  void initState() {
    super.initState();
    load();
  }

  @override
  void dispose() {
    timer?.cancel();
    countdown?.cancel();
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
          method = methods['credit'] == true ? 'credit' : 'fib';
        }
      });
      if (selectedExtension == null) {
        try {
          final configs = await widget.api.request('/payments/methods');
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
                    'review_required',
                  ].contains(o['status']),
                )
                .firstOrNull;
            if (pending != null) {
              order = Map<String, dynamic>.from(pending);
              submitted = true;
            }
          });
          if (order != null) startPolling();
          if (widget.api.user?['role'] == 'owner') await loadCards();
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
    countdown?.cancel();
    if (order != null &&
        ['pending', 'creating', 'activating'].contains(order!['status'])) {
      timer = Timer.periodic(const Duration(seconds: 5), (_) => checkPayment());
    }
    if (order?['status'] == 'pending' &&
        paymentDeadline != null &&
        !paymentWindowEnded) {
      countdown = Timer.periodic(const Duration(seconds: 1), (_) {
        if (!mounted || order?['status'] != 'pending') {
          countdown?.cancel();
          return;
        }
        setState(() {});
        if (paymentWindowEnded) {
          countdown?.cancel();
          checkPayment();
        }
      });
    }
  }

  Future<void> loadCards() async {
    setState(() {
      cardsLoading = true;
      cardsError = null;
      selectedCard = null;
    });
    try {
      final data = await widget.api.request(
        '/payments/users/${widget.userId}/radius-card',
      );
      if (!mounted) return;
      setState(() {
        savedCards = (data['items'] as List)
            .where(
              (card) =>
                  card['profile_id'] == info!['profile_id'] &&
                  card['price_iqd'] != null,
            )
            .toList();
        selectedCard = savedCards.isEmpty
            ? null
            : savedCards.first['id'] as String;
      });
    } catch (e) {
      if (mounted) {
        setState(() {
          savedCards = [];
          cardsError = e.toString();
        });
      }
    } finally {
      if (mounted) setState(() => cardsLoading = false);
    }
  }

  Future<void> getIssuedPin() async {
    if (submitting) return;
    setState(() {
      submitting = true;
      error = null;
    });
    try {
      final data = await widget.api.request(
        '/payments/orders/${order!['id']}/pin',
        method: 'POST',
      );
      if (mounted) setState(() => issuedPin = data['pin'] as String);
    } catch (e) {
      if (mounted) setState(() => error = e.toString());
    } finally {
      if (mounted) setState(() => submitting = false);
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
        countdown?.cancel();
        Navigator.pop(context, true);
      } else if (![
        'pending',
        'creating',
        'activating',
      ].contains(order!['status'])) {
        timer?.cancel();
        countdown?.cancel();
      }
    } catch (e) {
      if (mounted) setState(() => error = e.toString());
    } finally {
      polling = false;
    }
  }

  Future<void> checkFibConnection() async {
    setState(() {
      submitting = true;
      connectionMessage = null;
    });
    try {
      final result = await widget.api.request(
        '/payments/gateways/fib/test',
        method: 'POST',
        retry: false,
      );
      if (mounted) {
        setState(
          () => connectionMessage =
              '${result['environment']}: ${result['detail']}',
        );
      }
    } catch (e) {
      if (mounted) setState(() => connectionMessage = e.toString());
    } finally {
      if (mounted) setState(() => submitting = false);
    }
  }

  Future<void> retryCheckout() async {
    timer?.cancel();
    countdown?.cancel();
    setState(() {
      method = order!['provider'];
      order = null;
      issuedPin = null;
      connectionMessage = null;
      submitted = false;
      error = null;
    });
    await load();
  }

  Future<void> reviewCreation() async {
    bool checked = false;
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => StatefulBuilder(
        builder: (context, update) => AlertDialog(
          title: const AppText('Review unconfirmed payment'),
          content: SizedBox(
            width: 440,
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                const AppText(
                  'Check this attempt in FIB before releasing the card. If a payment exists or money was received, leave this order reserved to avoid a duplicate charge.',
                ),
                SelectableText(
                  'AirLink reference: ${order!['id']}\nAmount: ${order!['amount']} ${order!['currency']}',
                ),
                CheckboxListTile(
                  value: checked,
                  onChanged: (value) => update(() => checked = value == true),
                  title: const AppText(
                    'I checked FIB and confirmed no payment was created or paid.',
                  ),
                ),
              ],
            ),
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(context, false),
              child: const AppText('Cancel'),
            ),
            FilledButton(
              onPressed: checked ? () => Navigator.pop(context, true) : null,
              child: const AppText('Release reserved card'),
            ),
          ],
        ),
      ),
    );
    if (confirmed != true || !mounted) return;
    setState(() {
      submitting = true;
      error = null;
    });
    try {
      final data = await widget.api.request(
        '/payments/orders/${order!['id']}/review-creation',
        method: 'POST',
        retry: false,
        body: {'confirmed_not_created': true},
      );
      if (mounted) setState(() => order = Map<String, dynamic>.from(data));
    } catch (e) {
      if (mounted) setState(() => error = e.toString());
    } finally {
      if (mounted) setState(() => submitting = false);
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
            'expected_amount': method == 'fib'
                ? selectedCardData!['price_iqd']
                : info!['customer_price'],
            if (method != 'fib') 'expected_cost': info!['manager_cost'],
            'expected_profile_id': info!['profile_id'],
            'expected_expiration': info!['expiration'],
            if (method == 'fib') ...{
              'card_source': 'radius_pin',
              'radius_card_id': int.parse(selectedCard!),
              'radius_series': selectedCardData!['series'],
            },
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

  Widget paymentQr(String data) {
    const fallback = AppText(
      'QR image unavailable. Use the payment code below.',
    );
    Uint8List bytes;
    try {
      bytes = base64Decode(data.split(',').last);
    } on FormatException {
      return fallback;
    }
    return Center(
      child: Container(
        key: const ValueKey('bank-payment-qr'),
        margin: const EdgeInsets.symmetric(vertical: 8),
        padding: const EdgeInsets.all(16),
        color: Colors.white,
        child: Image.memory(
          bytes,
          width: 240,
          height: 240,
          fit: BoxFit.contain,
          filterQuality: FilterQuality.none,
          semanticLabel: tr('Scan this QR code with FIB Bank to pay'),
          errorBuilder: (_, _, _) => fallback,
        ),
      ),
    );
  }

  Widget paymentView() {
    final checkout = order!['checkout'] as Map? ?? {};
    final status = order!['status'];
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      mainAxisSize: MainAxisSize.min,
      children: [
        Text(
          order!['provider'] == 'fib' ? 'FIB Bank' : 'FastPay',
          style: const TextStyle(fontWeight: FontWeight.w600),
        ),
        Text(
          '${order!['amount']} ${order!['currency']}',
          key: const ValueKey('bank-payment-amount'),
          style: Theme.of(context).textTheme.headlineMedium,
        ),
        if (order!['profile'] != null) Text('Profile: ${order!['profile']}'),
        if (order!['card_label'] != null)
          Text('Recharge card: ${order!['card_label']}'),
        if (order!['environment'] == 'sandbox')
          const AppText(
            'Sandbox payment: no real PIN is issued or service recharged.',
          ),
        const SizedBox(height: 12),
        if (status == 'pending' && !paymentWindowEnded) ...[
          if (paymentSecondsLeft != null)
            Text(
              'Time left to pay: ${(paymentSecondsLeft! ~/ 60).toString().padLeft(2, '0')}:${(paymentSecondsLeft! % 60).toString().padLeft(2, '0')}',
              key: const ValueKey('fib-payment-countdown'),
              style: Theme.of(context).textTheme.titleLarge,
            ),
          if (order!['provider'] == 'fib') ...[
            const AppText('Scan this QR code with FIB Bank to pay'),
            const SizedBox(height: 8),
          ],
          AppText(
            order!['auto_recharge'] == true
                ? 'After FIB verifies payment, your reserved card will automatically recharge this customer.'
                : order!['fulfillment'] == 'saved_pin'
                ? 'After payment is verified, your reserved recharge PIN will be available here.'
                : 'Scan with the banking app to pay. Payment is verified automatically before service is recharged.',
          ),
          const SizedBox(height: 12),
          if (checkout['app_links'] is Map) ...[
            for (final kind in ['personal', 'business', 'corporate'])
              if (checkout['app_links'][kind] is String)
                Link(
                  uri: Uri.parse(checkout['app_links'][kind]),
                  target: LinkTarget.self,
                  builder: (context, followLink) => FilledButton.icon(
                    key: ValueKey('fib-pay-$kind'),
                    onPressed: followLink,
                    icon: const Icon(Icons.payment),
                    label: AppText(
                      kind == 'personal'
                          ? 'Pay with FIB'
                          : kind == 'business'
                          ? 'Pay with FIB Business'
                          : 'Pay with FIB Corporate',
                    ),
                  ),
                ),
            if (checkout['app_links']['personal'] is String)
              TextButton.icon(
                onPressed: () async {
                  await Clipboard.setData(
                    ClipboardData(text: checkout['app_links']['personal']),
                  );
                  if (mounted) {
                    ScaffoldMessenger.of(context).showSnackBar(
                      const SnackBar(
                        content: AppText(
                          'Payment link copied. Share it with the customer.',
                        ),
                      ),
                    );
                  }
                },
                icon: const Icon(Icons.copy),
                label: const AppText('Copy customer payment link'),
              ),
          ],
          if (order!['provider'] == 'fib')
            const AppText(
              'On Android or iPhone, tap Pay with FIB to open the payment in the FIB app. On another device, scan the QR code.',
            ),
          if (checkout['qr_data'] is String) paymentQr(checkout['qr_data']),
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
          'pending' =>
            paymentWindowEnded
                ? 'Payment window expired. Waiting for FIB confirmation. The recharge PIN remains locked.'
                : 'Waiting for payment…',
          'activating' => 'Payment verified. Recharging service…',
          'completed' => 'Payment verified and service recharged.',
          'pin_ready' => 'Payment verified. Your recharge PIN is ready.',
          'sandbox_paid' =>
            'Test payment verified. No real service was recharged.',
          'declined' => 'Payment declined or expired.',
          'expired' => 'Payment expired. No recharge PIN was issued or used.',
          _ =>
            order!['detail'] ??
                'Check the merchant portal before starting another payment.',
        }),
        if (order!['provider'] == 'fib' &&
            ['creation_failed', 'creation_unknown'].contains(status)) ...[
          if (connectionMessage != null) Text(connectionMessage!),
          Wrap(
            spacing: 8,
            children: [
              TextButton(
                onPressed: submitting ? null : checkFibConnection,
                child: const AppText('Check FIB connection'),
              ),
              TextButton(
                onPressed: submitting
                    ? null
                    : () => showDialog(
                        context: context,
                        builder: (context) => AlertDialog(
                          title: const AppText('Payment setup'),
                          content: SizedBox(
                            width: 520,
                            child: SingleChildScrollView(
                              child: PaymentSettings(
                                api: widget.api,
                                embedded: true,
                              ),
                            ),
                          ),
                          actions: [
                            TextButton(
                              onPressed: () => Navigator.pop(context),
                              child: const AppText('Close'),
                            ),
                          ],
                        ),
                      ),
                child: const AppText('Payment setup'),
              ),
            ],
          ),
          if (order!['can_review_creation'] == true)
            OutlinedButton(
              onPressed: submitting ? null : reviewCreation,
              child: const AppText('Review unconfirmed payment'),
            ),
        ],
        if (status == 'creation_failed' || status == 'expired')
          FilledButton(
            onPressed: submitting ? null : retryCheckout,
            child: AppText(
              status == 'expired'
                  ? 'Start new payment'
                  : 'Review price and retry',
            ),
          ),
        if (order!['status'] == 'pin_ready' &&
            order!['auto_recharge'] != true) ...[
          if (issuedPin == null)
            FilledButton(
              onPressed: submitting ? null : getIssuedPin,
              child: const AppText('Show recharge PIN'),
            ),
          if (issuedPin != null) ...[
            SelectableText(
              issuedPin!,
              key: const ValueKey('issued-recharge-pin'),
            ),
            Wrap(
              spacing: 8,
              children: [
                TextButton.icon(
                  onPressed: () async {
                    await Clipboard.setData(ClipboardData(text: issuedPin!));
                  },
                  icon: const Icon(Icons.copy),
                  label: const AppText('Copy PIN'),
                ),
                FilledButton.icon(
                  onPressed: () => setState(() {
                    pin.text = issuedPin!;
                    info = {...info!, 'transaction_id': order!['id']};
                    order = null;
                    issuedPin = null;
                    method = 'card';
                    submitted = false;
                    error = null;
                  }),
                  icon: const Icon(Icons.credit_card),
                  label: const AppText('Use PIN to recharge'),
                ),
              ],
            ),
          ],
        ],
        if (order!['detail'] != null &&
            ['pending', 'activating'].contains(status))
          Text(order!['detail']),
        const SizedBox(height: 8),
        SelectableText(
          'Reference: ${order!['id']}',
          style: const TextStyle(fontSize: 12),
        ),
        if (['pending', 'creating', 'activating'].contains(status))
          const AppText(
            'You can close this window. Payment checks continue on the server.',
            style: TextStyle(fontSize: 12),
          ),
      ],
    );
  }

  Widget rechargeMethods() {
    const types = [
      ('credit', 'Manager balance', Icons.account_balance_wallet_outlined),
      ('fib', 'FIB Bank', Icons.account_balance_outlined),
    ];
    bool selected(String type) => method == type;
    final colors = Theme.of(context).colorScheme;
    return Wrap(
      spacing: 10,
      runSpacing: 10,
      children: [
        for (final type in types)
          SizedBox(
            width: 104,
            height: 104,
            child: Semantics(
              selected: selected(type.$1),
              child: Material(
                color: selected(type.$1)
                    ? colors.primaryContainer
                    : colors.surface,
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(12),
                  side: BorderSide(
                    color: selected(type.$1)
                        ? colors.primary
                        : colors.outlineVariant,
                    width: selected(type.$1) ? 2 : 1,
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
                          color: selected(type.$1)
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
                              color: selected(type.$1)
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

  Widget cardPinSection() => Card.outlined(
    key: const ValueKey('recharge-pin-section'),
    margin: EdgeInsets.zero,
    child: Padding(
      padding: const EdgeInsets.all(16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        mainAxisSize: MainAxisSize.min,
        children: [
          AppText(
            'Recharge with PIN',
            style: Theme.of(context).textTheme.titleMedium,
          ),
          const SizedBox(height: 8),
          const AppText(
            'Enter the PIN from your recharge card, then press Recharge card.',
          ),
          const SizedBox(height: 16),
          TextFormField(
            key: const ValueKey('recharge-card-pin'),
            controller: pin,
            enabled: !loading && !submitted && permitted,
            obscureText: !showPin,
            autocorrect: false,
            enableSuggestions: false,
            textInputAction: TextInputAction.done,
            maxLength: 128,
            decoration: InputDecoration(
              labelText: tr('Card PIN'),
              counterText: '',
              border: const OutlineInputBorder(),
              suffixIcon: IconButton(
                tooltip: tr(showPin ? 'Hide PIN' : 'Show PIN'),
                onPressed: submitted
                    ? null
                    : () => setState(() => showPin = !showPin),
                icon: Icon(showPin ? Icons.visibility_off : Icons.visibility),
              ),
            ),
            validator: (value) =>
                value == null ||
                    value.trim().isEmpty ||
                    value.trim().runes.any((c) => c < 32)
                ? tr('Enter the card PIN')
                : null,
            onFieldSubmitted: (_) => recharge(),
          ),
        ],
      ),
    ),
  );

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
                        'Customer payment: ${method == 'fib' ? (selectedCardData?['price_iqd'] ?? 'Unavailable') : (info!['customer_price'] ?? 'Unavailable')} ${method == 'fib' ? 'IQD' : info!['currency'] ?? ''}',
                        key: const ValueKey('customer-payment-price'),
                        style: Theme.of(context).textTheme.headlineSmall,
                      ),
                      if (method != 'fib')
                        Text(
                          'SAS4 manager cost: ${info!['manager_cost'] ?? 'Unavailable'} ${info!['currency'] ?? ''}',
                        ),
                      Text(
                        gateways[method]['environment'] == 'sandbox'
                            ? 'Sandbox: no real PIN is issued or service recharged.'
                            : method == 'fib'
                            ? 'AirLink holds the selected SAS4 PIN for this payment. After FIB verifies payment, the PIN automatically recharges this customer.'
                            : 'Production: payment will be collected, then service recharged from your SAS4 manager balance.',
                      ),
                      if (method == 'fib') ...[
                        const SizedBox(height: 8),
                        const AppText(
                          'An unused SAS4 Radius PIN is selected for this customer’s current profile. FIB charges the SAS4 card value in IQD.',
                        ),
                        if (cardsLoading) const LinearProgressIndicator(),
                        if (cardsError != null) Text(cardsError!),
                        if (selectedCardData != null)
                          Text(
                            'Selected card: ${selectedCardData!['label']}',
                            key: const ValueKey('fib-selected-card'),
                          ),
                        if (!cardsLoading && savedCards.isEmpty)
                          const AppText(
                            'No unused SAS4 Radius card matches this profile. Add unused cards in SAS4 Radius, then refresh.',
                          ),
                        TextButton(
                          onPressed: cardsLoading ? null : loadCards,
                          child: const AppText('Refresh cards'),
                        ),
                        const AppText(
                          'Continue to show the customer their FIB Pay button, payment link, and QR code.',
                        ),
                      ],
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
                    if (method == 'card') cardPinSection(),
                    if (history.isNotEmpty) ...[
                      const Divider(height: 28),
                      const AppText('Recent payments'),
                      for (final payment in history)
                        ListTile(
                          contentPadding: EdgeInsets.zero,
                          dense: true,
                          title: Text(
                            '${payment['provider'] == 'fib' ? 'FIB Bank' : 'FastPay'} • ${payment['amount']} ${payment['currency']}',
                          ),
                          subtitle: Text('${payment['status']}'),
                          onTap: () {
                            setState(() {
                              issuedPin = null;
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
            icon: Icon(bank ? Icons.qr_code : Icons.credit_card),
            label: Text(
              submitting
                  ? 'Submitting…'
                  : method == 'fib'
                  ? 'Continue to FIB payment'
                  : method == 'fastpay'
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
