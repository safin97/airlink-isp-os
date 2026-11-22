import 'dart:async';
import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:url_launcher/link.dart';
import 'api.dart';
import 'app_language.dart';
import 'branding.dart';
import 'client_dashboard.dart';
import 'client_plan_card.dart';

class ClientPortal extends StatefulWidget {
  final Api? api;
  const ClientPortal({super.key, this.api});
  @override
  State<ClientPortal> createState() => _ClientPortalState();
}

class _ClientPortalState extends State<ClientPortal> with LanguageRebuild {
  late final Api api = widget.api ?? Api();
  final username = TextEditingController(),
      password = TextEditingController(),
      captcha = TextEditingController(),
      pin = TextEditingController();
  Map<String, dynamic>? account, options, card, order, selectedPackage;
  String? error, message, autoLoginNotice;
  bool busy = true, polling = false, fib = false, signedOut = false;
  Timer? timer;
  int selectedTab = 0;
  bool viewingCards = false;
  bool checkingPin = false;
  List<Map<String, dynamic>> catalog = [];
  String? catalogSyncedAt;
  final rechargeSectionKey = GlobalKey();
  final dashboardKey = GlobalKey<ClientDashboardState>();

  Future<dynamic> request(String path, {String method = 'GET', Object? body}) =>
      api.request('/client$path', method: method, body: body, retry: false);

  @override
  void initState() {
    super.initState();
    restore();
  }

  @override
  void dispose() {
    timer?.cancel();
    for (final controller in [username, password, captcha, pin]) {
      controller.dispose();
    }
    super.dispose();
  }

  Future<void> loginOptions() async {
    final result = await request('/login-options');
    if (mounted) setState(() => options = Map<String, dynamic>.from(result));
  }

  String automaticLoginExplanation(Map<String, dynamic> result) {
    final explanation = switch (result['reason']) {
      'outside_subscriber_ranges' =>
        'Your connection IP is outside the automatic-login ranges. Ask your provider to check the subscriber ranges and routing.',
      'local_connection' =>
        'Automatic login needs a customer ISP connection. It is unavailable from this local address.',
      'auto_login_disabled' =>
        'Automatic login is not configured. Sign in with your PPPoE username and password.',
      'stale_session' =>
        'Your SAS4 connection record is more than two minutes old. Ask your provider to check RADIUS accounting updates.',
      'ambiguous_session' =>
        'This IP matches more than one SAS4 session. Sign in with your username and password.',
      'accounting_clock_mismatch' =>
        'The SAS4 accounting time does not match the server clock. Ask your provider to check the server times.',
      'accounting_unavailable' || 'verification_unavailable' =>
        'Automatic login could not be verified. You can still try signing in with your username and password.',
      'account_unavailable' =>
        'Your account could not be verified for automatic login. Contact your provider or sign in manually.',
      'session_not_found' =>
        'No matching online SAS4 session was found for your connection. Sign in manually, or ask your provider to check the subscriber IP and accounting.',
      _ =>
        'Automatic login is unavailable for this connection. Sign in with your PPPoE username and password.',
    };
    final ip = result['source_ip'];
    return '${tr(explanation)}${ip is String && ip.isNotEmpty ? '\n${tr('Connection IP seen by AirLink')}: $ip' : ''}';
  }

  Future<void> restore() async {
    setState(() {
      busy = true;
      error = null;
      autoLoginNotice = null;
    });
    try {
      try {
        await loadAccount();
      } on ApiException catch (e) {
        if (e.status != 401) rethrow;
        Map<String, dynamic> result = {'authenticated': false};
        if (!signedOut) {
          try {
            result = Map<String, dynamic>.from(
              await request('/auto-login', method: 'POST'),
            );
          } catch (_) {
            result = {
              'authenticated': false,
              'reason': 'verification_unavailable',
            };
          }
        }
        if (result['authenticated'] == true) {
          await loadAccount();
        } else {
          if (mounted && !signedOut) {
            setState(() => autoLoginNotice = automaticLoginExplanation(result));
          }
          await loginOptions();
        }
      }
    } catch (e) {
      if (mounted) setState(() => error = e.toString());
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> loadAccount() async {
    final result = await request('/account');
    if (!mounted) return;
    setState(() {
      account = Map<String, dynamic>.from(result);
      final pending = (result['payments'] as List? ?? [])
          .where(
            (row) => [
              'creating',
              'pending',
              'activating',
              'paid_review',
              'creation_unknown',
              'review_required',
            ].contains(row['status']),
          )
          .firstOrNull;
      if (pending != null) {
        order = Map<String, dynamic>.from(pending);
        fib = true;
      }
    });
    watchPayment();
  }

  Future<void> signIn() async {
    if (busy ||
        options == null ||
        username.text.trim().isEmpty ||
        password.text.isEmpty) {
      return;
    }
    setState(() {
      busy = true;
      error = null;
      message = null;
    });
    try {
      await request(
        '/login',
        method: 'POST',
        body: {
          'username': username.text.trim(),
          'password': password.text,
          'challenge_id': options!['challenge_id'],
          'captcha_text': captcha.text.trim(),
        },
      );
      password.clear();
      captcha.clear();
      await loadAccount();
    } catch (e) {
      password.clear();
      captcha.clear();
      if (mounted) setState(() => error = e.toString());
      try {
        await loginOptions();
      } catch (_) {
        if (mounted) setState(() => options = null);
      }
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> signOut() async {
    if (busy) return;
    setState(() => busy = true);
    try {
      await request('/logout', method: 'POST');
      timer?.cancel();
      if (!mounted) return;
      setState(() {
        account = null;
        order = null;
        card = null;
        fib = false;
        signedOut = true;
        selectedTab = 0;
        viewingCards = false;
        selectedPackage = null;
        autoLoginNotice = null;
        catalog = [];
        catalogSyncedAt = null;
        error = null;
        message = null;
      });
      pin.clear();
      await loginOptions();
    } catch (e) {
      if (mounted) setState(() => error = e.toString());
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> loadCatalog() async {
    setState(() {
      busy = true;
      error = null;
      catalog = [];
      catalogSyncedAt = null;
    });
    try {
      await loadAccount();
      final data = await request('/cards');
      if (mounted) {
        setState(() {
          catalog = (data['items'] as List)
              .map((row) => Map<String, dynamic>.from(row))
              .toList();
          catalogSyncedAt = data['synced_at'];
        });
      }
    } catch (e) {
      if (mounted) setState(() => error = e.toString());
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> loadQuote() async {
    setState(() {
      busy = true;
      checkingPin = true;
      error = null;
      message = null;
      card = null;
    });
    try {
      await loadAccount();
      final data = await request(
        selectedPackage == null
            ? '/fib-quote'
            : '/fib-quote?package_profile_id=${selectedPackage!['profile_id']}',
      );
      if (mounted) {
        setState(
          () => card = (data['items'] as List).isEmpty
              ? null
              : Map<String, dynamic>.from(data['items'][0]),
        );
      }
    } catch (e) {
      if (mounted) setState(() => error = e.toString());
    } finally {
      if (mounted) {
        setState(() {
          busy = false;
          checkingPin = false;
        });
      }
    }
  }

  Future<void> submit() async {
    if (busy ||
        account == null ||
        account!['can_recharge'] != true ||
        order != null) {
      return;
    }
    if ((!fib && pin.text.trim().isEmpty) || (fib && card == null)) return;
    setState(() {
      busy = true;
      error = null;
      message = null;
    });
    try {
      final snapshot = {
        'transaction_id': account!['transaction_id'],
        'expected_profile_id': account!['profile_id'],
        'expected_expiration': account!['expiration'],
      };
      if (fib) {
        final result = await request(
          '/payments',
          method: 'POST',
          body: {
            ...snapshot,
            if (selectedPackage != null)
              'package_profile_id': selectedPackage!['profile_id'],
            'expected_amount': card!['price_iqd'],
            'radius_card_id': int.parse(card!['id']),
            'radius_series': card!['series'],
          },
        );
        if (mounted) setState(() => order = Map<String, dynamic>.from(result));
        watchPayment();
      } else {
        await request(
          '/recharge',
          method: 'POST',
          body: {...snapshot, 'pin': pin.text.trim()},
        );
        pin.clear();
        if (mounted) {
          setState(() => message = 'Your account was recharged successfully.');
        }
        await loadAccount();
      }
    } catch (e) {
      if (mounted) setState(() => error = e.toString());
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  void watchPayment() {
    timer?.cancel();
    if (order != null &&
        ['creating', 'pending', 'activating'].contains(order!['status'])) {
      timer = Timer.periodic(const Duration(seconds: 5), (_) => checkPayment());
    }
  }

  Future<void> checkPayment() async {
    if (polling || order == null) return;
    polling = true;
    try {
      final result = await request('/payments/${order!['id']}');
      if (!mounted) return;
      setState(() {
        order = Map<String, dynamic>.from(result);
        if (order!['status'] == 'completed') {
          selectedPackage = null;
          card = null;
          message = null;
        }
      });
      if (!['creating', 'pending', 'activating'].contains(order!['status'])) {
        timer?.cancel();
        if (order!['status'] == 'completed') await loadAccount();
      }
    } catch (e) {
      if (mounted) setState(() => error = e.toString());
    } finally {
      polling = false;
    }
  }

  Widget imageData(String? value, {double size = 220}) {
    try {
      if (value == null ||
          !RegExp(r'^data:image/(png|jpeg|gif|webp);base64,').hasMatch(value)) {
        return const SizedBox.shrink();
      }
      return Image.memory(
        base64Decode(value.split(',')[1]),
        width: size,
        height: size,
        errorBuilder: (_, error, stack) =>
            const AppText('Image unavailable. Refresh to try again.'),
      );
    } catch (_) {
      return const SizedBox.shrink();
    }
  }

  Widget payment([BuildContext? themedContext]) {
    final context = themedContext ?? this.context;
    final status = order!['status'];
    final expiry = DateTime.tryParse(order!['expires_at'] ?? '');
    final expired = expiry != null && !expiry.isAfter(DateTime.now());
    final checkout = order!['checkout'] as Map? ?? {};
    final link = checkout['app_links']?['personal'] as String?;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        if (order!['profile'] != null) ...[
          Text(
            '${order!['profile']}',
            style: Theme.of(context).textTheme.titleLarge,
          ),
          const SizedBox(height: 12),
        ],
        Text(
          '${order!['amount']} ${order!['currency']}',
          style: Theme.of(context).textTheme.headlineMedium,
        ),
        const SizedBox(height: 12),
        AppText(switch (status) {
          'completed' =>
            'Payment verified. Your internet account has been recharged.',
          'sandbox_paid' => 'Test payment verified. No real recharge was made.',
          'expired' => 'This payment expired. You can start a new payment.',
          'declined' => 'Payment was declined. You can start a new payment.',
          'creation_failed' =>
            'Payment could not be created. Review the amount and try again.',
          'activating' => 'Payment verified. Recharging your account…',
          'paid_review' || 'creation_unknown' || 'review_required' =>
            'This payment needs your provider’s review. Do not pay again.',
          _ =>
            expired
                ? 'Payment window ended. Waiting for bank confirmation.'
                : 'Complete your payment with FIB Bank.',
        }),
        if (order!['environment'] == 'sandbox')
          const AppText('Sandbox test — no real recharge'),
        if (status == 'pending' && !expired) ...[
          const SizedBox(height: 16),
          if (link != null && Uri.tryParse(link)?.scheme == 'https')
            Link(
              uri: Uri.parse(link),
              builder: (_, follow) => FilledButton.icon(
                onPressed: follow,
                icon: const Icon(Icons.account_balance),
                label: const AppText('Pay with FIB'),
              ),
            ),
          const SizedBox(height: 16),
          Center(child: imageData(checkout['qr_data'])),
          if (checkout['code'] != null)
            SelectableText(
              '${tr('Payment code')}: ${checkout['code']}',
              textAlign: TextAlign.center,
            ),
          if (expiry != null)
            Padding(
              padding: const EdgeInsets.only(top: 12),
              child: Text(
                '${tr('Time left')}: ${expiry.difference(DateTime.now()).inSeconds.clamp(0, 300)} s',
                textAlign: TextAlign.center,
              ),
            ),
        ],
        const SizedBox(height: 16),
        SelectableText(
          '${tr('Reference')}: ${order!['id']}',
          style: Theme.of(context).textTheme.bodySmall,
        ),
        if ([
          'completed',
          'sandbox_paid',
          'expired',
          'declined',
          'creation_failed',
        ].contains(status))
          TextButton(
            onPressed: busy
                ? null
                : () {
                    setState(() {
                      order = null;
                      card = null;
                    });
                    loadQuote();
                  },
            child: const AppText('Review recharge options'),
          ),
        TextButton(
          onPressed: checkPayment,
          child: const AppText('Refresh payment status'),
        ),
      ],
    );
  }

  String detail(dynamic value) {
    final text = value?.toString().trim() ?? '';
    return text.isEmpty ? '—' : text;
  }

  String get rechargeCost {
    final amount =
        order?['amount'] ??
        (fib ? (card?['price_iqd']) : (account?['recharge_cost']));
    final currency =
        order?['currency'] ?? (fib ? 'IQD' : (account?['currency']));
    if (detail(amount) == '—') return '—';
    return '${detail(amount)} ${currency ?? ''}'.trim();
  }

  void revealRecharge() {
    WidgetsBinding.instance.addPostFrameCallback((_) {
      final section = rechargeSectionKey.currentContext;
      if (mounted && selectedTab == 0 && section != null) {
        Scrollable.ensureVisible(
          section,
          duration: const Duration(milliseconds: 250),
          alignment: 0,
        );
      }
    });
  }

  Widget homeAction(IconData icon, String title, VoidCallback? onPressed) =>
      OutlinedButton(
        onPressed: onPressed,
        style: OutlinedButton.styleFrom(
          padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 16),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(16),
          ),
        ),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(icon, size: 28),
            const SizedBox(height: 8),
            Text(
              tr(title),
              textAlign: TextAlign.center,
              style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w600),
            ),
          ],
        ),
      );

  Widget homeActions() => Column(
    children: [
      Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Expanded(
            child: homeAction(
              Icons.credit_card,
              'Our Cards',
              busy
                  ? null
                  : () {
                      setState(() => viewingCards = true);
                      revealRecharge();
                      loadCatalog();
                    },
            ),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: homeAction(
              Icons.add_card,
              'Recharge',
              busy
                  ? null
                  : () {
                      setState(() {
                        viewingCards = false;
                        error = null;
                      });
                      revealRecharge();
                    },
            ),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Link(
              uri: Uri.parse('https://www.speedtest.net/'),
              target: LinkTarget.blank,
              builder: (_, follow) =>
                  homeAction(Icons.speed, 'SpeedTest', follow),
            ),
          ),
        ],
      ),
      const SizedBox(height: 12),
      const AppText(
        'SpeedTest opens speedtest.net. Tap GO there to begin.',
        textAlign: TextAlign.center,
      ),
      const SizedBox(height: 20),
    ],
  );

  Future<void> choosePackage(Map<String, dynamic> plan) async {
    if (busy) return;
    final outstanding =
        order != null &&
        ![
          'completed',
          'sandbox_paid',
          'expired',
          'declined',
          'creation_failed',
        ].contains(order!['status']);
    setState(() {
      selectedTab = 0;
      viewingCards = false;
      error = null;
      if (outstanding) {
        message =
            'Finish or resolve your existing payment before choosing another package.';
      } else {
        order = null;
        selectedPackage = Map<String, dynamic>.from(plan);
        fib = true;
        card = null;
        message = null;
      }
    });
    dashboardKey.currentState?.showRecharge();
    if (!outstanding) await loadQuote();
  }

  Widget availableCards([BuildContext? themedContext]) {
    final context = themedContext ?? this.context;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text(tr('Our Cards'), style: Theme.of(context).textTheme.titleLarge),
        const SizedBox(height: 8),
        const AppText('AirLink plans synced from SAS4 Radius.'),
        const SizedBox(height: 20),
        if (!busy && error == null && catalog.isEmpty)
          const AppText(
            'No AirLink plans are available. Please refresh or contact your provider.',
          ),
        for (final plan in catalog)
          ClientPlanCard(
            plan: plan,
            current: plan['profile_id'] == account!['profile_id'],
            onRecharge:
                !busy &&
                    account!['can_recharge'] == true &&
                    account!['fib_configured'] == true
                ? () => choosePackage(plan)
                : null,
          ),
        if (catalog.isNotEmpty)
          const AppText(
            'Tap Pay to choose a package. Your SAS4 service changes only after FIB confirms payment. FIB charges the available card value shown at checkout.',
          ),
        if (catalogSyncedAt != null)
          Padding(
            padding: const EdgeInsets.only(top: 12),
            child: Text(
              '${tr('Updated')}: ${DateTime.tryParse(catalogSyncedAt!)?.toLocal().toString().split('.').first ?? '—'}',
            ),
          ),
        const SizedBox(height: 12),
        TextButton(
          onPressed: busy ? null : loadCatalog,
          child: const AppText('Refresh cards'),
        ),
      ],
    );
  }

  Widget homePage() => SafeArea(
    child: Center(
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 620),
        child: ListView(
          key: const PageStorageKey("client-home"),
          padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 24),
          children: [
            if (account == null) ...[
              const Center(child: AirLinkLogo(width: 220)),
              const SizedBox(height: 24),
            ],
            Text(
              account == null
                  ? tr('Client recharge')
                  : tr('Your internet service'),
              style: Theme.of(context).textTheme.headlineMedium,
              textAlign: TextAlign.center,
            ),
            const SizedBox(height: 8),
            AppText(
              account == null
                  ? 'Sign in to recharge your internet account.'
                  : 'Your internet account, ready to recharge.',
              textAlign: TextAlign.center,
            ),
            const SizedBox(height: 24),
            if (account != null) homeActions(),
            Card.outlined(
              key: rechargeSectionKey,
              child: Padding(
                padding: const EdgeInsets.all(24),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    if (busy) const LinearProgressIndicator(),
                    if (error != null)
                      Padding(
                        padding: const EdgeInsets.symmetric(vertical: 12),
                        child: Text(
                          error!,
                          style: TextStyle(
                            color: Theme.of(context).colorScheme.error,
                          ),
                        ),
                      ),
                    if (message != null)
                      Padding(
                        padding: const EdgeInsets.symmetric(vertical: 12),
                        child: Text(message!),
                      ),
                    if (account == null) ...[
                      const SizedBox(height: 16),
                      AutofillGroup(
                        child: Column(
                          children: [
                            TextField(
                              controller: username,
                              enabled: !busy,
                              autofillHints: const [AutofillHints.username],
                              decoration: InputDecoration(
                                labelText: tr('PPPoE username'),
                                border: const OutlineInputBorder(),
                              ),
                              textInputAction: TextInputAction.next,
                            ),
                            const SizedBox(height: 16),
                            TextField(
                              controller: password,
                              enabled: !busy,
                              obscureText: true,
                              enableSuggestions: false,
                              autocorrect: false,
                              autofillHints: const [AutofillHints.password],
                              decoration: InputDecoration(
                                labelText: tr('Password'),
                                border: const OutlineInputBorder(),
                              ),
                              onSubmitted: (_) => signIn(),
                            ),
                          ],
                        ),
                      ),
                      if (options?['captcha_image'] != null) ...[
                        const SizedBox(height: 16),
                        Center(
                          child: imageData(
                            options!['captcha_image'],
                            size: 150,
                          ),
                        ),
                        TextField(
                          controller: captcha,
                          decoration: InputDecoration(
                            labelText: tr('Verification code'),
                          ),
                        ),
                      ],
                      const SizedBox(height: 20),
                      FilledButton(
                        onPressed: busy || options == null ? null : signIn,
                        child: AppText(busy ? 'Connecting…' : 'Sign in'),
                      ),
                      if (options == null && !busy)
                        TextButton(
                          onPressed: restore,
                          child: const AppText('Retry connection'),
                        ),
                      if (autoLoginNotice != null) ...[
                        const SizedBox(height: 16),
                        Text(autoLoginNotice!),
                      ],
                      const SizedBox(height: 16),
                      const AppText(
                        'On your ISP connection, we can sign you in automatically when your account is identified. On mobile data, use your username and password.',
                        textAlign: TextAlign.center,
                      ),
                    ] else ...[
                      const SizedBox(height: 16),
                      const AppText('Username'),
                      Text(
                        account!['username'],
                        style: Theme.of(context).textTheme.titleLarge,
                      ),
                      const SizedBox(height: 8),
                      Text(
                        '${tr('Service profile')}: ${detail(account!['profile'])}',
                      ),
                      const SizedBox(height: 8),
                      Text('${tr('Recharge cost')}: $rechargeCost'),
                      const SizedBox(height: 8),
                      Text('${tr('Expiry')}: ${account!['expiration'] ?? '—'}'),
                      const Divider(height: 32),
                      if (viewingCards)
                        availableCards()
                      else if (order != null)
                        payment()
                      else ...[
                        Wrap(
                          spacing: 12,
                          runSpacing: 8,
                          children: [
                            ChoiceChip(
                              label: const AppText('Recharge PIN'),
                              selected: !fib,
                              onSelected: busy
                                  ? null
                                  : (_) => setState(() {
                                      fib = false;
                                      error = null;
                                    }),
                            ),
                            ChoiceChip(
                              label: const AppText('FIB Bank'),
                              selected: fib,
                              onSelected:
                                  busy || account!['fib_configured'] != true
                                  ? null
                                  : (_) {
                                      setState(() => fib = true);
                                      loadQuote();
                                    },
                            ),
                          ],
                        ),
                        const SizedBox(height: 20),
                        if (fib && checkingPin)
                          const Padding(
                            padding: EdgeInsets.only(bottom: 16),
                            child: AppText('Checking SAS4 for an unused PIN…'),
                          ),
                        if (!fib)
                          TextField(
                            controller: pin,
                            enabled: !busy,
                            obscureText: true,
                            enableSuggestions: false,
                            autocorrect: false,
                            decoration: InputDecoration(
                              labelText: tr('Card PIN'),
                              border: const OutlineInputBorder(),
                            ),
                          ),
                        if (fib && card != null) ...[
                          const Row(
                            children: [
                              Icon(Icons.check_circle_outline, size: 20),
                              SizedBox(width: 8),
                              Expanded(child: AppText('Unused PIN available')),
                            ],
                          ),
                          const SizedBox(height: 12),
                          Text(
                            '${card!['price_iqd']} IQD',
                            style: Theme.of(context).textTheme.headlineMedium,
                          ),
                          const SizedBox(height: 8),
                          const AppText(
                            'An unused SAS4 card will recharge your account after FIB confirms your payment.',
                          ),
                        ],
                        if (fib && card == null && !busy && error == null)
                          const AppText(
                            'No unused PIN is available for your service. Refresh availability or contact your internet provider.',
                          ),
                        if (account!['can_recharge'] != true)
                          const AppText(
                            'Self-service recharge is not enabled. Contact your internet provider.',
                          ),
                        const SizedBox(height: 20),
                        FilledButton(
                          onPressed:
                              busy ||
                                  account!['can_recharge'] != true ||
                                  (fib && card == null)
                              ? null
                              : submit,
                          child: AppText(
                            checkingPin
                                ? 'Checking unused PIN…'
                                : busy
                                ? 'Please wait…'
                                : fib
                                ? 'Continue to FIB payment'
                                : 'Recharge my account',
                          ),
                        ),
                        if (fib)
                          TextButton(
                            onPressed: busy ? null : loadQuote,
                            child: const AppText('Refresh card availability'),
                          ),
                      ],
                    ],
                  ],
                ),
              ),
            ),
            const SizedBox(height: 16),
            const AppText(
              'AirLink • Customer self-service',
              textAlign: TextAlign.center,
            ),
          ],
        ),
      ),
    ),
  );

  Widget rechargePanel(BuildContext context) => Column(
    crossAxisAlignment: CrossAxisAlignment.stretch,
    children: [
      if (selectedPackage != null && order == null) ...[
        const AppText('Selected package'),
        Text(
          '${selectedPackage!['name']}',
          style: Theme.of(context).textTheme.titleLarge,
        ),
        const SizedBox(height: 8),
        const AppText(
          'This package will be activated after FIB confirms your payment.',
        ),
        const SizedBox(height: 20),
      ],
      if (order != null)
        payment(context)
      else ...[
        Wrap(
          spacing: 12,
          runSpacing: 8,
          children: [
            ChoiceChip(
              label: const AppText('Recharge PIN'),
              selected: !fib,
              onSelected: busy
                  ? null
                  : (_) => setState(() {
                      fib = false;
                      selectedPackage = null;
                      card = null;
                      error = null;
                    }),
            ),
            ChoiceChip(
              label: const AppText('FIB Bank'),
              selected: fib,
              onSelected: busy || account!['fib_configured'] != true
                  ? null
                  : (_) {
                      setState(() => fib = true);
                      loadQuote();
                    },
            ),
          ],
        ),
        const SizedBox(height: 20),
        if (fib && checkingPin)
          const Padding(
            padding: EdgeInsets.only(bottom: 16),
            child: AppText('Checking SAS4 for an unused PIN…'),
          ),
        if (!fib)
          TextField(
            controller: pin,
            enabled: !busy,
            obscureText: true,
            enableSuggestions: false,
            autocorrect: false,
            decoration: InputDecoration(
              labelText: tr('Card PIN'),
              border: const OutlineInputBorder(),
            ),
          ),
        if (fib && card != null) ...[
          const Row(
            children: [
              Icon(Icons.check_circle_outline, size: 20),
              SizedBox(width: 8),
              Expanded(child: AppText('Unused PIN available')),
            ],
          ),
          const SizedBox(height: 12),
          Text(
            '${card!['price_iqd']} IQD',
            style: Theme.of(context).textTheme.headlineMedium,
          ),
          const SizedBox(height: 8),
          const AppText(
            'An unused SAS4 card will recharge your account after FIB confirms your payment.',
          ),
        ],
        if (fib && card == null && !busy && error == null)
          AppText(
            selectedPackage == null
                ? 'No unused PIN is available for your service. Refresh availability or contact your internet provider.'
                : 'No unused PIN is available for this package. Choose another package or contact your internet provider.',
          ),
        if (account!['can_recharge'] != true)
          const AppText(
            'Self-service recharge is not enabled. Contact your internet provider.',
          ),
        const SizedBox(height: 20),
        FilledButton(
          onPressed:
              busy || account!['can_recharge'] != true || (fib && card == null)
              ? null
              : submit,
          child: AppText(
            checkingPin
                ? 'Checking unused PIN…'
                : busy
                ? 'Please wait…'
                : fib
                ? 'Continue to FIB payment'
                : 'Recharge my account',
          ),
        ),
        if (fib)
          TextButton(
            onPressed: busy ? null : loadQuote,
            child: const AppText('Refresh card availability'),
          ),
      ],
    ],
  );

  Future<void> refreshDashboard() async {
    if (busy) return;
    setState(() {
      busy = true;
      error = null;
    });
    try {
      await loadAccount();
      if (selectedTab == 2) await loadCatalog();
    } catch (e) {
      if (mounted) setState(() => error = e.toString());
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  void selectClientTab(int index) {
    setState(() => selectedTab = index);
    if (index == 2) loadCatalog();
  }

  Widget pageBody(String storageKey, List<Widget> children) => SafeArea(
    child: Center(
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 620),
        child: ListView(
          key: PageStorageKey(storageKey),
          padding: const EdgeInsets.all(20),
          children: children,
        ),
      ),
    ),
  );

  Widget profilePage(BuildContext context) => pageBody('client-profile', [
    Card.outlined(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            CircleAvatar(
              radius: 32,
              backgroundColor: Theme.of(context).colorScheme.primaryContainer,
              child: const Icon(Icons.person_outline, size: 36),
            ),
            const SizedBox(height: 16),
            Text(
              account!['username'],
              textAlign: TextAlign.center,
              style: Theme.of(context).textTheme.headlineSmall,
            ),
            const SizedBox(height: 24),
            for (final field in [
              ('Username', account!['username']),
              ('First name', account!['first_name']),
              ('Last name', account!['last_name']),
              ('Phone number', account!['phone']),
              ('Service profile', account!['profile']),
              (
                'Recharge cost',
                '${detail(account!['recharge_cost'])} ${account!['currency'] ?? ''}'
                    .trim(),
              ),
              ('Expiry', account!['expiration']),
            ])
              Padding(
                padding: const EdgeInsets.only(bottom: 16),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      tr(field.$1),
                      style: Theme.of(context).textTheme.labelLarge,
                    ),
                    const SizedBox(height: 4),
                    SelectableText(
                      detail(field.$2),
                      style: Theme.of(context).textTheme.bodyLarge,
                    ),
                  ],
                ),
              ),
            const AppText(
              'To update your details, contact your internet provider.',
            ),
            const SizedBox(height: 20),
            if (error != null)
              Text(
                error!,
                style: TextStyle(color: Theme.of(context).colorScheme.error),
              ),
            OutlinedButton.icon(
              onPressed: busy ? null : signOut,
              icon: const Icon(Icons.logout),
              label: AppText(busy ? 'Please wait…' : 'Sign out'),
            ),
          ],
        ),
      ),
    ),
  ]);

  Widget aboutPage(BuildContext context) => pageBody('client-about', [
    Card.outlined(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            const Center(child: AirLinkLogo(width: 200)),
            const SizedBox(height: 24),
            Text(
              'AirLink',
              textAlign: TextAlign.center,
              style: Theme.of(context).textTheme.headlineMedium,
            ),
            const SizedBox(height: 8),
            const AppText(
              'Telecommunication company',
              textAlign: TextAlign.center,
            ),
            const SizedBox(height: 24),
            const AppText(
              'Welcome to your AirLink customer portal. Manage your internet service and check your connection in one place.',
            ),
            const SizedBox(height: 20),
            const ListTile(
              contentPadding: EdgeInsets.zero,
              leading: Icon(Icons.home_outlined),
              title: AppText('Recharge your service'),
              subtitle: AppText(
                'Use a recharge PIN or pay with FIB Bank from Home.',
              ),
            ),
            const ListTile(
              contentPadding: EdgeInsets.zero,
              leading: Icon(Icons.wifi),
              title: AppText('Check your connection'),
              subtitle: AppText(
                'Open Usage for wireless signal and internet checks, or start a speed test from Home.',
              ),
            ),
            const ListTile(
              contentPadding: EdgeInsets.zero,
              leading: Icon(Icons.person_outline),
              title: AppText('Your account details'),
              subtitle: AppText(
                'View your service and contact details in Profile.',
              ),
            ),
            const Divider(height: 32),
            const AppText(
              'For account or service support, contact your internet provider.',
            ),
          ],
        ),
      ),
    ),
  ]);

  @override
  Widget build(BuildContext context) => account == null
      ? Scaffold(body: homePage())
      : ClientDashboard(
          key: dashboardKey,
          api: api,
          account: account!,
          selectedTab: selectedTab,
          busy: busy,
          error: error,
          message: message,
          onRefresh: refreshDashboard,
          onTab: selectClientTab,
          recharge: rechargePanel,
          packages: (context) => availableCards(context),
          profile: profilePage,
          support: aboutPage,
        );
}
