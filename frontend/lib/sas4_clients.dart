import 'dart:async';
import 'dart:convert';
import 'package:flutter/material.dart';
import 'api.dart';
import 'sas4_user_details.dart';

class Sas4Clients extends StatefulWidget {
  final Api api;
  final bool showDashboard;
  final bool showOnline;
  const Sas4Clients({
    super.key,
    required this.api,
    this.showDashboard = true,
    this.showOnline = false,
  });
  @override
  State<Sas4Clients> createState() => _Sas4ClientsState();
}

class _Sas4ClientsState extends State<Sas4Clients> {
  final search = TextEditingController();
  Timer? refreshTimer;
  bool busy = true;
  bool backgroundFetching = false;
  bool viewingUser = false;
  int requestVersion = 0;
  bool configured = false;
  String? error;
  Map<String, dynamic>? result;
  Map<String, dynamic>? dashboard;
  bool viewingDashboard = true;
  bool onlineOnly = false;
  String currentSearch = '';
  bool get canConnect =>
      ['owner', 'manager'].contains(widget.api.user?['role']);

  @override
  void initState() {
    super.initState();
    viewingDashboard = widget.showDashboard;
    onlineOnly = widget.showOnline;
    if (canConnect) {
      loadConnection();
      refreshTimer = Timer.periodic(const Duration(seconds: 30), (_) {
        if (configured && !busy && !backgroundFetching && !viewingUser) {
          fetch(
            page: viewingDashboard ? 1 : result?['page'] as int? ?? 1,
            quiet: true,
          );
        }
      });
    } else {
      busy = false;
    }
  }

  @override
  void dispose() {
    refreshTimer?.cancel();
    search.dispose();
    super.dispose();
  }

  Future<void> loadConnection() async {
    try {
      final data = await widget.api.request('/integrations/sas4');
      if (!mounted) return;
      setState(() {
        configured = data['configured'] == true;
      });
      if (configured) await fetch();
    } catch (e) {
      if (mounted) setState(() => error = e.toString());
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> fetch({
    int page = 1,
    bool newSearch = false,
    bool quiet = false,
  }) async {
    if (quiet && (busy || backgroundFetching)) return;
    final version = ++requestVersion;
    if (quiet) {
      backgroundFetching = true;
    } else {
      setState(() {
        busy = true;
        error = null;
      });
    }
    if (newSearch) currentSearch = search.text.trim();
    try {
      final path = viewingDashboard
          ? '/integrations/sas4/dashboard'
          : '/integrations/sas4/${onlineOnly ? 'online' : 'clients'}?page=$page&search=${Uri.encodeQueryComponent(currentSearch)}';
      final data = Map<String, dynamic>.from(await widget.api.request(path));
      if (!mounted || version != requestVersion) return;
      final previous = viewingDashboard ? dashboard : result;
      // Fetch timestamps alone should not redraw the displayed data.
      final comparable = Map<String, dynamic>.from(data)..remove('fetched_at');
      final old = previous == null
          ? null
          : (Map<String, dynamic>.from(previous)..remove('fetched_at'));
      if (!quiet ||
          error != null ||
          jsonEncode(comparable) != jsonEncode(old)) {
        setState(() {
          if (viewingDashboard) {
            dashboard = data;
          } else {
            result = data;
          }
          error = null;
        });
      }
    } catch (e) {
      if (mounted && version == requestVersion) {
        final message =
            quiet && (viewingDashboard ? dashboard != null : result != null)
            ? 'Refresh failed; showing previously fetched data. $e'
            : e.toString();
        if (error != message) setState(() => error = message);
      }
    } finally {
      if (quiet) backgroundFetching = false;
      if (!quiet && mounted && version == requestVersion) {
        setState(() => busy = false);
      }
    }
  }

  Future<void> openUser(dynamic row) async {
    final id = int.tryParse('${row['id']}');
    if (id == null || id < 1 || viewingUser) return;
    viewingUser = true;
    final saved = await Navigator.of(context).push<bool>(
      MaterialPageRoute(
        builder: (_) => Sas4UserDetails(api: widget.api, userId: id),
      ),
    );
    viewingUser = false;
    if (mounted && saved == true) {
      fetch(page: result?['page'] as int? ?? 1, quiet: true);
    }
  }

  Widget dashboardCards() {
    final cards = [
      (
        'Total users',
        'total_users',
        Icons.people_outline,
        const Color(0xff438fff),
      ),
      (
        'Active users',
        'active_users',
        Icons.verified_user_outlined,
        const Color(0xff34d399),
      ),
      ('Online users', 'online_users', Icons.wifi, const Color(0xff38bdf8)),
      (
        'Expired users',
        'expired_users',
        Icons.event_busy_outlined,
        const Color(0xffff7385),
      ),
      (
        'About to expire',
        'about_to_expire',
        Icons.schedule,
        const Color(0xffffb454),
      ),
      (
        'Balance',
        'balance',
        Icons.account_balance_wallet_outlined,
        const Color(0xffa78bfa),
      ),
      (
        'Reward points',
        'reward_points',
        Icons.stars_outlined,
        const Color(0xfffacc15),
      ),
    ];
    return LayoutBuilder(
      builder: (context, constraints) {
        final columns = (constraints.maxWidth / 180).floor().clamp(1, 6);
        final side = ((constraints.maxWidth - (columns - 1) * 12) / columns)
            .clamp(0.0, 190.0)
            .toDouble();
        return Wrap(
          spacing: 12,
          runSpacing: 12,
          children: cards.map((card) {
            final value = dashboard?[card.$2];
            return SizedBox(
              width: side,
              height: side,
              child: Card(
                margin: EdgeInsets.zero,
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(16),
                  side: BorderSide(color: card.$4.withValues(alpha: .3)),
                ),
                child: Padding(
                  padding: const EdgeInsets.all(16),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Icon(card.$3, color: card.$4, size: 26),
                      const Spacer(),
                      Text(
                        card.$1,
                        style: const TextStyle(
                          fontWeight: FontWeight.w600,
                          fontSize: 14,
                        ),
                      ),
                      const SizedBox(height: 8),
                      SizedBox(
                        width: double.infinity,
                        child: FittedBox(
                          fit: BoxFit.scaleDown,
                          alignment: Alignment.centerLeft,
                          child: Text(
                            value == null ? '—' : '$value',
                            style: TextStyle(
                              fontSize: 30,
                              fontWeight: FontWeight.w700,
                              color: card.$4,
                            ),
                          ),
                        ),
                      ),
                      const SizedBox(height: 6),
                      Text(
                        value == null
                            ? (busy ? 'Loading…' : 'Unavailable')
                            : card.$2 == 'about_to_expire'
                            ? 'SAS4 expiry window'
                            : ['balance', 'reward_points'].contains(card.$2)
                            ? 'Your SAS4 account'
                            : 'From SAS4',
                        style: const TextStyle(
                          fontSize: 12,
                          color: Color(0xff99acc6),
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            );
          }).toList(),
        );
      },
    );
  }

  String text(dynamic value) =>
      value == null || value.toString().isEmpty ? '—' : value.toString();
  String statusLabel(dynamic row) {
    final status = text(row['status']);
    if (row['online'] == false && (status == 'active' || status == 'expired')) {
      return '$status • offline';
    }
    return status;
  }

  Color statusColor(dynamic status) => switch (status) {
    'online' => const Color(0xff38bdf8),
    'active • online' => const Color(0xff438fff),
    'active • offline' => const Color(0xff34d399),
    'expired' || 'expired • offline' => const Color(0xffff7385),
    'expired • online' => const Color(0xffffb454),
    'limited' ||
    'limited • online' ||
    'expired / limited • online' => const Color(0xfffacc15),
    'disabled • online' => const Color(0xffb09acb),
    'active' => const Color(0xff99acc6),
    'disabled' => const Color(0xffff7385),
    'expired / limited' => const Color(0xffffb454),
    _ => const Color(0xff99acc6),
  };

  @override
  Widget build(BuildContext context) {
    if (!canConnect) {
      return const Text(
        'Manager access is required to connect and view SAS4 clients.',
      );
    }
    final rows = (result?['clients'] as List?) ?? [];
    final page = result?['page'] as int? ?? 1;
    final lastPage = result?['last_page'] as int? ?? 1;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Text(
          viewingDashboard
              ? 'ISP Card • Dashboard'
              : onlineOnly
              ? 'ISP Card • Online users'
              : 'ISP Card • Users list',
          style: TextStyle(
            fontSize: viewingDashboard ? 24 : 20,
            fontWeight: FontWeight.w600,
          ),
        ),
        const SizedBox(height: 8),
        Text(
          'Your SAS4 account • Refreshes every 30 seconds',
          style: TextStyle(fontSize: viewingDashboard ? null : 13),
        ),
        SizedBox(height: viewingDashboard ? 16 : 8),
        if (!busy && !configured)
          const Padding(
            padding: EdgeInsets.symmetric(vertical: 20),
            child: Text(
              'Open My account at the top right to set up your SAS4 connection.',
            ),
          ),
        if (error != null)
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 16),
            child: Text(
              error!,
              style: TextStyle(color: Theme.of(context).colorScheme.error),
            ),
          ),
        if (busy)
          const Padding(
            padding: EdgeInsets.symmetric(vertical: 16),
            child: LinearProgressIndicator(),
          ),
        if (viewingDashboard) ...[
          const SizedBox(height: 20),
          dashboardCards(),
          for (final warning in (dashboard?['warnings'] as List? ?? []))
            Padding(
              padding: const EdgeInsets.only(top: 12),
              child: Text(
                '$warning',
                style: const TextStyle(color: Color(0xffffb454)),
              ),
            ),
          if (dashboard?['fetched_at'] != null)
            Padding(
              padding: const EdgeInsets.only(top: 12),
              child: Text(
                'Fetched ${DateTime.tryParse(dashboard!['fetched_at'])?.toLocal().toString().split('.').first ?? 'now'}',
                style: const TextStyle(fontSize: 12, color: Color(0xff99acc6)),
              ),
            ),
        ],
        if (configured && !viewingDashboard) ...[
          const SizedBox(height: 12),
          Wrap(
            spacing: 8,
            runSpacing: 6,
            crossAxisAlignment: WrapCrossAlignment.center,
            children: [
              SizedBox(
                width: 240,
                child: TextField(
                  controller: search,
                  style: const TextStyle(fontSize: 14),
                  enabled: !busy,
                  decoration: const InputDecoration(
                    isDense: true,
                    contentPadding: EdgeInsets.symmetric(
                      horizontal: 10,
                      vertical: 10,
                    ),
                    prefixIconConstraints: BoxConstraints(
                      minWidth: 34,
                      minHeight: 34,
                    ),
                    prefixIcon: Icon(Icons.search, size: 18),
                    hintText: 'Search users',
                  ),
                  onSubmitted: (_) => fetch(newSearch: true),
                ),
              ),
              FilledButton(
                style: FilledButton.styleFrom(
                  textStyle: const TextStyle(fontSize: 14),
                  minimumSize: const Size(0, 32),
                  padding: const EdgeInsets.symmetric(horizontal: 10),
                  visualDensity: VisualDensity.compact,
                ),
                onPressed: busy ? null : () => fetch(newSearch: true),
                child: const Text('Search'),
              ),
              OutlinedButton.icon(
                style: OutlinedButton.styleFrom(
                  textStyle: const TextStyle(fontSize: 14),
                  minimumSize: const Size(0, 32),
                  padding: const EdgeInsets.symmetric(horizontal: 10),
                  visualDensity: VisualDensity.compact,
                ),
                onPressed: busy ? null : () => fetch(page: page),
                icon: const Icon(Icons.refresh, size: 16),
                label: const Text('Refresh users'),
              ),
            ],
          ),
        ],
        if (result != null && !viewingDashboard) ...[
          const SizedBox(height: 12),
          Text(
            '${result!['total']} ${onlineOnly ? 'online users' : 'users'}',
            style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 16),
          ),
          if (rows.isEmpty)
            const Padding(
              padding: EdgeInsets.all(24),
              child: Text('No users match this search.'),
            )
          else
            SingleChildScrollView(
              scrollDirection: Axis.horizontal,
              child: DataTable(
                showCheckboxColumn: false,
                headingRowHeight: 36,
                dataRowMinHeight: 34,
                dataRowMaxHeight: 38,
                horizontalMargin: 10,
                columnSpacing: 24,
                headingTextStyle: TextStyle(
                  fontSize: 14,
                  fontWeight: FontWeight.w600,
                  color: Theme.of(context).colorScheme.onSurface,
                ),
                dataTextStyle: TextStyle(
                  fontSize: 14,
                  color: Theme.of(context).colorScheme.onSurface,
                ),
                columns: [
                  for (final label in [
                    'Username',
                    'Name',
                    'Profile',
                    'Status',
                    if (onlineOnly) 'IP address',
                    'Expiration',
                    'SAS4 manager',
                  ])
                    DataColumn(label: Text(label)),
                ],
                rows: rows
                    .map(
                      (row) => DataRow(
                        cells: [
                          DataCell(
                            Text(
                              text(row['username']),
                              style: TextStyle(
                                color: statusColor(statusLabel(row)),
                                fontWeight: FontWeight.w600,
                              ),
                            ),
                            onTap: row['id'] == null
                                ? null
                                : () => openUser(row),
                          ),
                          DataCell(Text(text(row['name']))),
                          DataCell(Text(text(row['profile']))),
                          DataCell(
                            Text(
                              statusLabel(row),
                              style: TextStyle(
                                color: statusColor(statusLabel(row)),
                              ),
                            ),
                          ),
                          if (onlineOnly)
                            DataCell(SelectableText(text(row['ip_address']))),
                          DataCell(Text(text(row['expiration']))),
                          DataCell(Text(text(row['manager']))),
                        ],
                      ),
                    )
                    .toList(),
              ),
            ),
          const SizedBox(height: 12),
          Wrap(
            spacing: 8,
            crossAxisAlignment: WrapCrossAlignment.center,
            children: [
              TextButton.icon(
                style: TextButton.styleFrom(
                  textStyle: const TextStyle(fontSize: 14),
                  minimumSize: const Size(0, 32),
                  padding: const EdgeInsets.symmetric(horizontal: 10),
                  visualDensity: VisualDensity.compact,
                ),
                onPressed: busy || page <= 1
                    ? null
                    : () => fetch(page: page - 1),
                icon: const Icon(Icons.chevron_left, size: 16),
                label: const Text('Previous'),
              ),
              Text(
                'Page $page of $lastPage',
                style: const TextStyle(fontSize: 14),
              ),
              TextButton.icon(
                style: TextButton.styleFrom(
                  textStyle: const TextStyle(fontSize: 14),
                  minimumSize: const Size(0, 32),
                  padding: const EdgeInsets.symmetric(horizontal: 10),
                  visualDensity: VisualDensity.compact,
                ),
                onPressed: busy || page >= lastPage
                    ? null
                    : () => fetch(page: page + 1),
                icon: const Icon(Icons.chevron_right, size: 16),
                label: const Text('Next'),
              ),
              Text(
                'Fetched ${DateTime.tryParse(result!['fetched_at'] ?? '')?.toLocal().toString().split('.').first ?? 'now'}',
                style: const TextStyle(fontSize: 12, color: Color(0xff99acc6)),
              ),
            ],
          ),
        ],
      ],
    );
  }
}
