import 'dart:async';
import 'package:flutter/material.dart';
import 'api.dart';
import 'app_language.dart';
import 'branding.dart';
import 'client_connection.dart';
import 'client_dashboard_style.dart';
import 'client_speed_gauge.dart';

/// SAS4 timestamps without an offset use the ISP's Iraq time zone.
DateTime? clientSubscriptionExpiry(dynamic value) {
  var text = value?.toString().trim() ?? '';
  if (text.isEmpty) return null;
  if (RegExp(r'^\d{4}-\d{2}-\d{2}$').hasMatch(text)) text += 'T00:00:00';
  if (!RegExp(r'(Z|[+-]\d{2}:?\d{2})$', caseSensitive: false).hasMatch(text)) {
    text += '+03:00';
  }
  return DateTime.tryParse(text);
}

class ClientDashboard extends StatefulWidget {
  final Api api;
  final Map<String, dynamic> account;
  final int selectedTab;
  final bool busy;
  final String? error, message;
  final Future<void> Function() onRefresh;
  final ValueChanged<int> onTab;
  final WidgetBuilder recharge, packages, profile, support;
  const ClientDashboard({
    super.key,
    required this.api,
    required this.account,
    required this.selectedTab,
    required this.busy,
    this.error,
    this.message,
    required this.onRefresh,
    required this.onTab,
    required this.recharge,
    required this.packages,
    required this.profile,
    required this.support,
  });
  @override
  State<ClientDashboard> createState() => ClientDashboardState();
}

class ClientDashboardState extends State<ClientDashboard> {
  final rechargeKey = GlobalKey();
  Timer? ticker;
  @override
  void initState() {
    super.initState();
    ticker = Timer.periodic(const Duration(minutes: 1), (_) {
      if (mounted) setState(() {});
    });
  }

  @override
  void dispose() {
    ticker?.cancel();
    super.dispose();
  }

  String detail(dynamic value) =>
      value == null || value.toString().trim().isEmpty ? '—' : value.toString();
  DateTime? get expiry =>
      clientSubscriptionExpiry(widget.account['expiration']);
  bool get expired => expiry != null && !expiry!.isAfter(DateTime.now());
  String get status => expiry == null
      ? 'Status unavailable'
      : expired
      ? 'Expired'
      : 'Active';
  String get remaining {
    if (expiry == null) return '—';
    final duration = expiry!.difference(DateTime.now());
    if (duration.isNegative) return tr('Expired');
    return '${duration.inDays}d ${duration.inHours % 24}h ${duration.inMinutes % 60}m';
  }

  String get expiryLabel {
    final date = expiry?.toLocal();
    if (date == null) return '—';
    String two(int n) => n.toString().padLeft(2, '0');
    return '${date.year}-${two(date.month)}-${two(date.day)} · ${two(date.hour)}:${two(date.minute)} (local)';
  }

  void showRecharge() => WidgetsBinding.instance.addPostFrameCallback((_) {
    if (mounted) reveal(rechargeKey);
  });

  void reveal(GlobalKey key) {
    final context = key.currentContext;
    if (context != null) {
      Scrollable.ensureVisible(
        context,
        duration: const Duration(milliseconds: 350),
        curve: Curves.easeOutCubic,
      );
    }
  }

  void showSpeedTest(BuildContext context) {
    final speedKey = GlobalKey<ClientSpeedGaugeState>();
    showDialog<void>(
      context: context,
      builder: (context) => Dialog(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 600),
          child: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Align(
                  alignment: Alignment.centerRight,
                  child: IconButton(
                    tooltip: tr('Close'),
                    onPressed: () => Navigator.of(context).pop(),
                    icon: Icon(Icons.close),
                  ),
                ),
                ClientSpeedGauge(key: speedKey),
              ],
            ),
          ),
        ),
      ),
    );
    WidgetsBinding.instance.addPostFrameCallback((_) {
      speedKey.currentState?.start();
    });
  }

  void notices(BuildContext context) => showModalBottomSheet<void>(
    context: context,
    showDragHandle: true,
    isScrollControlled: true,
    builder: (context) => SafeArea(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Text(
                tr('Account notifications'),
                style: Theme.of(context).textTheme.titleLarge,
              ),
              const SizedBox(height: 20),
              Text('${tr('Subscription')}: ${tr(status)}'),
              const SizedBox(height: 8),
              Text('${tr('Expiry')}: $expiryLabel'),
              if (expired)
                const AppText(
                  'Your subscription has expired. Recharge from Home to renew your service.',
                ),
              const Divider(height: 32),
              if ((widget.account['payments'] as List? ?? []).isEmpty)
                const AppText('No recent payment updates.'),
              for (final payment
                  in (widget.account['payments'] as List? ?? []).take(5))
                ListTile(
                  contentPadding: EdgeInsets.zero,
                  leading: Icon(Icons.receipt_long_outlined),
                  title: Text(
                    '${detail(payment['amount'])} ${detail(payment['currency'])}',
                  ),
                  subtitle: Text(
                    '${tr('Payment status')}: ${detail(payment['status']).replaceAll('_', ' ')}',
                  ),
                ),
            ],
          ),
        ),
      ),
    ),
  );

  Widget header(BuildContext context) => Padding(
    padding: const EdgeInsets.fromLTRB(20, 16, 12, 12),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        const Wrap(
          alignment: WrapAlignment.end,
          crossAxisAlignment: WrapCrossAlignment.center,
          children: [LanguageSelector(), ThemeToggle()],
        ),
        const SizedBox(height: 8),
        Row(
          children: [
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  LayoutBuilder(
                    builder: (context, constraints) => AirLinkLogo(
                      width: constraints.maxWidth < 160
                          ? constraints.maxWidth
                          : 160,
                    ),
                  ),
                  const SizedBox(height: 14),
                  Text(
                    tr('Welcome back'),
                    style: TextStyle(color: clientMuted, fontSize: 14),
                  ),
                  Text(
                    detail(widget.account['username']),
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: Theme.of(context).textTheme.headlineSmall,
                  ),
                ],
              ),
            ),
            IconButton(
              tooltip: tr('Refresh account'),
              onPressed: widget.busy ? null : widget.onRefresh,
              icon: Icon(Icons.refresh_rounded),
            ),
            IconButton(
              tooltip: tr('Notifications'),
              onPressed: () => notices(context),
              icon: Icon(Icons.notifications_none_rounded),
            ),
            IconButton(
              tooltip: tr('Open profile'),
              onPressed: () => widget.onTab(4),
              icon: CircleAvatar(
                radius: 18,
                backgroundColor: clientColor(0xff234568, 0xffdceafb),
                child: Icon(
                  Icons.person_outline_rounded,
                  color: clientCyan,
                  size: 22,
                ),
              ),
            ),
          ],
        ),
      ],
    ),
  );

  Widget quickAction(IconData icon, String label, VoidCallback action) =>
      Expanded(
        child: OutlinedButton(
          onPressed: action,
          style: OutlinedButton.styleFrom(
            backgroundColor: clientColor(0xff102b47, 0xffe6f0fc),
            side: BorderSide(color: clientColor(0xff2c5076, 0xffbbd2e7)),
            padding: const EdgeInsets.symmetric(vertical: 16, horizontal: 4),
          ),
          child: Column(
            children: [
              Icon(icon, color: clientCyan, size: 26),
              const SizedBox(height: 9),
              Text(
                tr(label),
                textAlign: TextAlign.center,
                style: TextStyle(
                  fontSize: 14,
                  color: clientColor(0xffffffff, 0xff163456),
                ),
              ),
            ],
          ),
        ),
      );

  Widget subscription(BuildContext context) => ClientGlass(
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Row(
          children: [
            Icon(Icons.wifi_rounded, color: clientCyan),
            const SizedBox(width: 10),
            Expanded(
              child: Text(
                tr('Your subscription'),
                style: Theme.of(context).textTheme.titleLarge,
              ),
            ),
          ],
        ),
        const SizedBox(height: 18),
        Align(
          alignment: Alignment.centerLeft,
          child: Container(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
            decoration: BoxDecoration(
              color:
                  (expired
                          ? clientColor(0xffff667d, 0xffb4233d)
                          : expiry == null
                          ? clientMuted
                          : clientColor(0xff69efc5, 0xff087858))
                      .withValues(alpha: .12),
              borderRadius: BorderRadius.circular(30),
            ),
            child: Text(
              tr(status),
              style: TextStyle(
                fontWeight: FontWeight.w700,
                color: expired
                    ? clientColor(0xffff8294, 0xffb4233d)
                    : expiry == null
                    ? clientMuted
                    : clientColor(0xff69efc5, 0xff087858),
              ),
            ),
          ),
        ),
        const SizedBox(height: 20),
        for (final field in [
          ('Username', detail(widget.account['username'])),
          ('Service profile', detail(widget.account['profile'])),
          (
            'Recharge cost',
            '${detail(widget.account['recharge_cost'])} ${widget.account['currency'] ?? ''}'
                .trim(),
          ),
          ('Expiry', expiryLabel),
          ('Time remaining', remaining),
        ])
          Padding(
            padding: const EdgeInsets.only(bottom: 16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  tr(field.$1),
                  style: TextStyle(color: clientMuted, fontSize: 14),
                ),
                const SizedBox(height: 4),
                Text(
                  field.$2,
                  style: TextStyle(fontSize: 16, fontWeight: FontWeight.w600),
                ),
              ],
            ),
          ),
        if (expired)
          FilledButton.icon(
            onPressed: () => reveal(rechargeKey),
            icon: Icon(Icons.add_card),
            label: const AppText('Recharge now'),
          ),
      ],
    ),
  );

  Widget home(BuildContext context) => LayoutBuilder(
    builder: (context, constraints) {
      final wide = constraints.maxWidth >= 850;
      final recharge = ClientGlass(
        key: rechargeKey,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(
              tr('Recharge your service'),
              style: Theme.of(context).textTheme.titleLarge,
            ),
            const SizedBox(height: 8),
            const AppText('Stay connected with a PIN or FIB Bank.'),
            const SizedBox(height: 20),
            widget.recharge(context),
          ],
        ),
      );
      return SingleChildScrollView(
        key: const PageStorageKey('dashboard-home'),
        physics: const AlwaysScrollableScrollPhysics(),
        padding: const EdgeInsets.fromLTRB(20, 8, 20, 28),
        child: Column(
          children: [
            if (expired)
              Padding(
                padding: const EdgeInsets.only(bottom: 16),
                child: Container(
                  padding: const EdgeInsets.all(16),
                  decoration: BoxDecoration(
                    color: clientColor(0xff3d1c2c, 0xffffe8ed),
                    borderRadius: BorderRadius.circular(18),
                  ),
                  child: Row(
                    children: [
                      Icon(
                        Icons.error_outline,
                        color: clientColor(0xffff8294, 0xffb4233d),
                      ),
                      const SizedBox(width: 12),
                      const Expanded(
                        child: AppText(
                          'Your subscription has expired. Recharge to renew your service.',
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            Row(
              children: [
                quickAction(
                  Icons.speed_rounded,
                  'SpeedTest',
                  () => showSpeedTest(context),
                ),
                const SizedBox(width: 10),
                quickAction(
                  Icons.add_card_rounded,
                  'Recharge',
                  () => reveal(rechargeKey),
                ),
                const SizedBox(width: 10),
                quickAction(
                  Icons.credit_card_rounded,
                  'Our Cards',
                  () => widget.onTab(2),
                ),
              ],
            ),
            const SizedBox(height: 22),
            if (wide)
              Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Expanded(child: subscription(context)),
                  const SizedBox(width: 22),
                  Expanded(child: recharge),
                ],
              )
            else ...[
              subscription(context),
              const SizedBox(height: 22),
              recharge,
            ],
            const SizedBox(height: 24),
            AppText(
              'AirLink • Customer self-service',
              style: TextStyle(color: clientMuted),
            ),
          ],
        ),
      );
    },
  );

  @override
  Widget build(BuildContext context) => Theme(
    data: clientDashboardTheme(),
    child: Builder(
      builder: (context) => Scaffold(
        body: Container(
          decoration: BoxDecoration(
            gradient: RadialGradient(
              center: Alignment.topRight,
              radius: 1.4,
              colors: [clientColor(0xff13375d, 0xffe0efff), clientNavy],
              stops: [0, .75],
            ),
          ),
          child: SafeArea(
            child: Center(
              child: ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 1100),
                child: Column(
                  children: [
                    header(context),
                    if (widget.busy)
                      const LinearProgressIndicator(minHeight: 2),
                    if (widget.error != null || widget.message != null)
                      Padding(
                        padding: const EdgeInsets.symmetric(
                          horizontal: 20,
                          vertical: 8,
                        ),
                        child: Text(
                          widget.error ?? widget.message!,
                          style: TextStyle(
                            color: widget.error != null
                                ? clientColor(0xffff8294, 0xffb4233d)
                                : clientCyan,
                          ),
                        ),
                      ),
                    Expanded(
                      child: RefreshIndicator(
                        onRefresh: widget.onRefresh,
                        child: switch (widget.selectedTab) {
                          1 => ListView(
                            padding: const EdgeInsets.all(20),
                            physics: const AlwaysScrollableScrollPhysics(),
                            children: [
                              Text(
                                tr('My connection'),
                                style: Theme.of(
                                  context,
                                ).textTheme.headlineSmall,
                              ),
                              const SizedBox(height: 8),
                              const AppText(
                                'Data usage totals are not available from your provider.',
                              ),
                              const SizedBox(height: 20),
                              ClientConnection(api: widget.api),
                            ],
                          ),
                          2 => SingleChildScrollView(
                            physics: const AlwaysScrollableScrollPhysics(),
                            padding: const EdgeInsets.all(20),
                            child: widget.packages(context),
                          ),
                          3 => widget.support(context),
                          4 => widget.profile(context),
                          _ => home(context),
                        },
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ),
        ),
        bottomNavigationBar: DecoratedBox(
          decoration: BoxDecoration(
            border: Border(
              top: BorderSide(color: clientColor(0xff234563, 0xffcddce9)),
            ),
          ),
          child: NavigationBarTheme(
            data: const NavigationBarThemeData(
              labelTextStyle: WidgetStatePropertyAll(
                TextStyle(fontSize: 14, fontWeight: FontWeight.w500),
              ),
            ),
            child: NavigationBar(
              backgroundColor: clientColor(0xff091a2d, 0xffffffff),
              indicatorColor: clientColor(0xff1d466c, 0xffd4e8fc),
              selectedIndex: widget.selectedTab,
              onDestinationSelected: widget.onTab,
              labelBehavior: NavigationDestinationLabelBehavior.alwaysShow,
              destinations: [
                for (final item in [
                  ('Home', Icons.home_rounded),
                  ('Usage', Icons.bar_chart_rounded),
                  ('Packages', Icons.credit_card_rounded),
                  ('Support', Icons.support_agent_rounded),
                  ('Profile', Icons.person_outline_rounded),
                ])
                  NavigationDestination(
                    icon: Icon(item.$2),
                    label: tr(item.$1),
                  ),
              ],
            ),
          ),
        ),
      ),
    ),
  );
}
