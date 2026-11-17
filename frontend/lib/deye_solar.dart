import 'dart:async';
import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';
import 'api.dart';
import 'deye_sharing.dart';
import 'deye_energy_overview.dart';

class DeyeSolar extends StatefulWidget {
  const DeyeSolar({
    super.key,
    required this.api,
    this.dashboard = false,
    this.onOpen,
  });
  final Api api;
  final bool dashboard;
  final VoidCallback? onOpen;
  @override
  State<DeyeSolar> createState() => _DeyeSolarState();
}

class _DeyeSolarState extends State<DeyeSolar> {
  final account = TextEditingController();
  final password = TextEditingController();
  final appId = TextEditingController();
  final appSecret = TextEditingController();
  final country = TextEditingController();
  final company = TextEditingController();
  String region = 'eu', loginType = 'email';
  bool configured = false, editing = false, busy = true;
  String? error, stationId;
  int page = 1, total = 0;
  List<Map<String, dynamic>> stations = [];
  Map<String, dynamic>? reading;
  Map<String, dynamic>? dashboardStation;
  Timer? timer, liveWatchdog;
  bool liveHealthy = false, backgroundRefresh = false;
  String? liveStationId;
  static const refreshInterval = Duration(seconds: 5);
  StreamSubscription<Map<String, dynamic>>? liveSubscription;
  Map<String, dynamic>? pendingLive;
  static const base = '/integrations/deye';
  bool get canEdit => widget.api.user?['role'] == 'owner';
  bool get canDelete => canEdit;

  @override
  void initState() {
    super.initState();
    liveSubscription = widget.api.liveEvents.listen(onLive);
    load();
  }

  @override
  void dispose() {
    timer?.cancel();
    liveSubscription?.cancel();
    liveWatchdog?.cancel();
    for (final controller in [
      account,
      password,
      appId,
      appSecret,
      country,
      company,
    ]) {
      controller.dispose();
    }
    super.dispose();
  }

  void onLive(Map<String, dynamic> event) {
    if (!mounted) return;
    if (event['type'] == 'connection' && event['connected'] == false) {
      liveHealthy = false;
      liveWatchdog?.cancel();
    } else if (['snapshot', 'patch', 'heartbeat'].contains(event['type'])) {
      liveHealthy = true;
      liveWatchdog?.cancel();
      liveWatchdog = Timer(
        const Duration(seconds: 10),
        () => liveHealthy = false,
      );
    }
    if (!event.containsKey('deye')) return;
    final data = event['deye'];
    if (data is! Map) {
      timer?.cancel();
      setState(() {
        configured = false;
        reading = null;
        stationId = null;
        editing = false;
      });
      return; // Parent removes the view when access is revoked.
    }
    final frame = Map<String, dynamic>.from(data);
    liveStationId = (frame['dashboard_station'] as Map?)?['id']?.toString();
    if (busy) {
      pendingLive = frame;
      return;
    }
    applyLive(frame);
  }

  void applyLive(Map<String, dynamic> frame) {
    if (!mounted || editing) return;
    setState(() {
      configured = frame['configured'] == true;
      if (!configured) {
        timer?.cancel();
        reading = null;
        stationId = null;
        stations = [];
        error = null;
        if (!widget.dashboard) editing = canEdit;
        return;
      }
      if (widget.dashboard && frame['dashboard_station'] is Map) {
        final selected = Map<String, dynamic>.from(frame['dashboard_station']);
        if (stationId != selected['id']) reading = null;
        stationId = selected['id'];
        stations = [selected];
      }
      final values = frame['readings'];
      final current = values is Map ? values[stationId] : null;
      if (widget.dashboard && frame['monitor_error'] != null) {
        error = frame['monitor_error'].toString();
        reading = gridHistoryOnly(current is Map ? current : reading);
      } else if (current is Map) {
        // An HTTP response and a live frame can cross in flight.
        final incoming = DateTime.tryParse(
          current['fetched_at']?.toString() ?? '',
        );
        final displayed = DateTime.tryParse(
          reading?['fetched_at']?.toString() ?? '',
        );
        if (incoming != null &&
            displayed != null &&
            incoming.isBefore(displayed)) {
          return;
        }
        error = current['error']?.toString();
        reading = error == null
            ? Map<String, dynamic>.from(current)
            : gridHistoryOnly(current);
      }
    });
    // Healthy live views receive readings through the socket, without HTTP reloads.
    if (configured &&
        !editing &&
        stationId != null &&
        !(timer?.isActive ?? false)) {
      timer = Timer(refreshInterval, autoRefresh);
    }
  }

  Map<String, dynamic>? gridHistoryOnly(dynamic values) {
    final grid = values is Map ? values['grid_availability'] : null;
    if (grid is! Map) return null;
    return {
      'grid_availability': {
        ...grid,
        'state': 'unknown',
        'current_outage_seconds': null,
        'current_outage_started_at': null,
      },
    };
  }

  void schedule() {
    final frame = pendingLive;
    pendingLive = null;
    if (frame != null) applyLive(frame);
    timer?.cancel();
    if (configured && !editing && stationId != null) {
      timer = Timer(refreshInterval, autoRefresh);
    }
  }

  void autoRefresh() {
    if (busy || editing || !configured || stationId == null) return;
    if (liveHealthy && (widget.dashboard || liveStationId == stationId)) {
      schedule();
      return;
    }
    // Other selected stations and disconnected streams update quietly in place.
    refresh(silent: true);
  }

  Future<void> load() async {
    setState(() {
      busy = true;
      error = null;
    });
    try {
      final result = await widget.api.request(base);
      if (!mounted) return;
      if (result is! Map) {
        throw const FormatException(
          'Deye connection status is unavailable. Try again.',
        );
      }
      configured = result['configured'] == true;
      editing = !configured && !widget.dashboard && canEdit;
      if (configured) {
        if (canEdit) {
          region = result['region'];
          loginType = result['login_type'];
          account.text = result['account'];
          appId.text = result['app_id'];
          country.text = result['country_code'] ?? '';
          company.text = result['company_id']?.toString() ?? '';
        }
        dashboardStation = result['dashboard_station'] == null
            ? null
            : Map<String, dynamic>.from(result['dashboard_station']);
        if (widget.dashboard) {
          await fetchDashboard(result);
        } else {
          page = dashboardStation?['page'] ?? 1;
          stationId = dashboardStation?['id'];
          await fetchStations();
        }
      }
    } catch (e) {
      if (mounted) error = e.toString();
    } finally {
      if (mounted) {
        setState(() => busy = false);
        schedule();
      }
    }
  }

  Future<void> fetchStations({bool first = false}) async {
    final result = await widget.api.request('$base/stations?page=$page');
    if (!mounted) return;
    stations = List<Map<String, dynamic>>.from(result['stations']);
    total = result['total'];
    final previous = stationId;
    if (first || !stations.any((s) => s['id'] == stationId)) {
      stationId = stations.isEmpty ? null : stations.first['id'];
    }
    if (previous != stationId) reading = null;
    await fetchReading();
  }

  Future<void> fetchDashboard([dynamic settings]) async {
    final result = settings ?? await widget.api.request(base);
    if (!mounted) return;
    configured = result['configured'] == true;
    dashboardStation = result['dashboard_station'] == null
        ? null
        : Map<String, dynamic>.from(result['dashboard_station']);
    if (!configured) {
      stationId = null;
      reading = null;
      stations = [];
      return;
    }
    if (dashboardStation != null) {
      if (stationId != dashboardStation!['id']) reading = null;
      stationId = dashboardStation!['id'];
      stations = [dashboardStation!];
      total = 1;
      await fetchReading();
    } else {
      page = 1;
      await fetchStations(first: true);
    }
  }

  Future<void> saveDashboardStation({bool automatic = false}) async {
    if (!canEdit || busy || (!automatic && stationId == null)) return;
    timer?.cancel();
    setState(() {
      busy = true;
      error = null;
    });
    try {
      final result = await widget.api.request(
        '$base/dashboard-station',
        method: 'PUT',
        retry: false,
        body: {'station_id': automatic ? null : stationId, 'page': page},
      );
      if (!mounted) return;
      dashboardStation = result['dashboard_station'] == null
          ? null
          : Map<String, dynamic>.from(result['dashboard_station']);
    } catch (e) {
      if (mounted) error = e.toString();
    } finally {
      if (mounted) {
        setState(() => busy = false);
        schedule();
      }
    }
  }

  Future<void> fetchReading() async {
    final selected = stationId;
    if (selected == null) {
      reading = null;
      return;
    }
    final result = await widget.api.request('$base/stations/$selected/latest');
    if (mounted && selected == stationId) {
      reading = Map<String, dynamic>.from(result);
    }
  }

  Future<void> refresh({bool inventory = false, bool silent = false}) async {
    if (busy) return;
    timer?.cancel();
    setState(() {
      busy = true;
      backgroundRefresh = silent;
      if (!silent) error = null;
    });
    try {
      if (widget.dashboard) {
        await fetchDashboard();
      } else if (inventory) {
        await fetchStations();
      } else {
        await fetchReading();
      }
      if (mounted) error = null;
    } catch (e) {
      if (mounted) {
        error = e.toString();
        reading = gridHistoryOnly(reading);
      }
    } finally {
      if (mounted) {
        setState(() {
          busy = false;
          backgroundRefresh = false;
        });
        schedule();
      }
    }
  }

  Future<void> save() async {
    if (account.text.trim().isEmpty ||
        appId.text.trim().isEmpty ||
        (!configured && (password.text.isEmpty || appSecret.text.isEmpty)) ||
        (company.text.isNotEmpty && int.tryParse(company.text) == null)) {
      setState(
        () => error =
            'Enter your Deye account, password, App ID and App Secret. Company ID must be numeric if provided.',
      );
      return;
    }
    setState(() {
      busy = true;
      error = null;
    });
    try {
      final result = await widget.api.request(
        base,
        method: 'PUT',
        retry: false,
        body: {
          'region': region,
          'login_type': loginType,
          'account': account.text.trim(),
          'country_code': country.text.trim(),
          'app_id': appId.text.trim(),
          'company_id': company.text.trim().isEmpty
              ? null
              : int.parse(company.text.trim()),
          if (password.text.isNotEmpty) 'password': password.text,
          if (appSecret.text.isNotEmpty) 'app_secret': appSecret.text,
        },
      );
      if (!mounted) return;
      password.clear();
      appSecret.clear();
      configured = true;
      editing = false;
      dashboardStation = result['dashboard_station'] == null
          ? null
          : Map<String, dynamic>.from(result['dashboard_station']);
      page = dashboardStation?['page'] ?? 1;
      stationId = dashboardStation?['id'];
      reading = null;
      await fetchStations();
    } catch (e) {
      if (mounted) error = e.toString();
    } finally {
      if (mounted) {
        setState(() => busy = false);
        schedule();
      }
    }
  }

  Future<void> disconnect() async {
    final accepted = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Disconnect Deye Cloud?'),
        content: const Text(
          'Remove this AirLink account’s saved Deye login and cached readings. Your inverter and Deye Cloud account stay unchanged.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('Disconnect'),
          ),
        ],
      ),
    );
    if (accepted != true || !mounted) return;
    timer?.cancel();
    setState(() {
      busy = true;
      error = null;
    });
    try {
      await widget.api.request(base, method: 'DELETE', retry: false);
      if (!mounted) return;
      configured = false;
      dashboardStation = null;
      editing = true;
      reading = null;
      stations = [];
      stationId = null;
      password.clear();
      appSecret.clear();
    } catch (e) {
      if (mounted) error = e.toString();
    } finally {
      if (mounted) {
        setState(() => busy = false);
        schedule();
      }
    }
  }

  Widget field(
    TextEditingController controller,
    String label, {
    bool secret = false,
    String? hint,
  }) => Padding(
    padding: const EdgeInsets.only(bottom: 12),
    child: TextField(
      controller: controller,
      enabled: !busy,
      obscureText: secret,
      autocorrect: false,
      enableSuggestions: !secret,
      decoration: InputDecoration(
        labelText: label,
        helperText: hint,
        helperMaxLines: 3,
        border: const OutlineInputBorder(),
      ),
    ),
  );

  Widget connectionForm() => Card(
    child: Padding(
      padding: const EdgeInsets.all(20),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text(
            'Connect your Deye Cloud account',
            style: TextStyle(fontSize: 20, fontWeight: FontWeight.w600),
          ),
          const SizedBox(height: 8),
          const Text(
            'Use the same account as the Deye Cloud app, plus an App ID and App Secret from Deye’s developer portal with station monitoring access.',
          ),
          TextButton.icon(
            onPressed: () => launchUrl(
              Uri.parse('https://developer.deyecloud.com/'),
              mode: LaunchMode.externalApplication,
            ),
            icon: const Icon(Icons.open_in_new, size: 16),
            label: const Text('Deye developer portal'),
          ),
          const SizedBox(height: 8),
          DropdownButtonFormField<String>(
            initialValue: region,
            isExpanded: true,
            decoration: const InputDecoration(
              labelText: 'Deye Cloud region',
              border: OutlineInputBorder(),
            ),
            items: const [
              DropdownMenuItem(
                value: 'eu',
                child: Text(
                  'Europe / EMEA / Asia-Pacific',
                  overflow: TextOverflow.ellipsis,
                ),
              ),
              DropdownMenuItem(value: 'am', child: Text('Americas')),
              DropdownMenuItem(value: 'india', child: Text('India')),
            ],
            onChanged: busy ? null : (value) => setState(() => region = value!),
          ),
          const SizedBox(height: 12),
          DropdownButtonFormField<String>(
            initialValue: loginType,
            isExpanded: true,
            decoration: const InputDecoration(
              labelText: 'Login with',
              border: OutlineInputBorder(),
            ),
            items: const [
              DropdownMenuItem(value: 'email', child: Text('Email')),
              DropdownMenuItem(value: 'username', child: Text('Username')),
              DropdownMenuItem(value: 'mobile', child: Text('Mobile number')),
            ],
            onChanged: busy
                ? null
                : (value) => setState(() => loginType = value!),
          ),
          const SizedBox(height: 12),
          field(account, 'Deye Cloud account'),
          if (loginType == 'mobile')
            field(country, 'Country code (digits only)'),
          field(
            password,
            'Deye Cloud password',
            secret: true,
            hint: configured ? 'Leave blank to keep the saved password.' : null,
          ),
          field(appId, 'App ID'),
          field(
            appSecret,
            'App Secret',
            secret: true,
            hint: configured ? 'Leave blank to keep the saved secret.' : null,
          ),
          field(
            company,
            'Company ID (optional)',
            hint:
                'For a business organization; leave blank for your personal account.',
          ),
          const Text(
            'Credentials are encrypted on the AirLink server. This dashboard only reads monitoring data.',
          ),
          const SizedBox(height: 12),
          Wrap(
            spacing: 12,
            children: [
              FilledButton.icon(
                onPressed: busy || !canEdit ? null : save,
                icon: const Icon(Icons.login),
                label: Text(busy ? 'Connecting…' : 'Connect Deye Cloud'),
              ),
              if (configured)
                TextButton(
                  onPressed: busy
                      ? null
                      : () {
                          setState(() => editing = false);
                          schedule();
                        },
                  child: const Text('Back to energy overview'),
                ),
            ],
          ),
        ],
      ),
    ),
  );

  Widget status() {
    final recent = reading?['freshness'] == 'recent';
    final stale = reading?['freshness'] == 'stale';
    final dark = Theme.of(context).brightness == Brightness.dark;
    final color = recent
        ? (dark ? Colors.tealAccent.shade100 : Colors.teal.shade800)
        : stale
        ? (dark ? Colors.orange.shade200 : Colors.orange.shade900)
        : Theme.of(context).colorScheme.onSurfaceVariant;
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 7),
      decoration: BoxDecoration(
        color: color.withValues(alpha: .12),
        borderRadius: BorderRadius.circular(24),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(
            recent
                ? Icons.cloud_done_outlined
                : stale
                ? Icons.history
                : Icons.cloud_off_outlined,
            color: color,
            size: 16,
          ),
          const SizedBox(width: 7),
          Flexible(
            child: Text(
              recent
                  ? 'Recent cloud reading'
                  : stale
                  ? 'Stale cloud reading — check inverter connectivity'
                  : 'Reading time unavailable',
              style: TextStyle(
                color: color,
                fontSize: 12,
                fontWeight: FontWeight.w600,
              ),
            ),
          ),
        ],
      ),
    );
  }

  String observedTime(BuildContext context) {
    final stamp = DateTime.tryParse(
      reading?['observed_at']?.toString() ?? '',
    )?.toLocal();
    if (stamp == null) return 'Unavailable';
    final labels = MaterialLocalizations.of(context);
    return '${labels.formatMediumDate(stamp)} · ${labels.formatTimeOfDay(TimeOfDay.fromDateTime(stamp))}';
  }

  @override
  Widget build(BuildContext context) => Container(
    width: double.infinity,
    padding: EdgeInsets.all(widget.dashboard ? 16 : 20),
    decoration: BoxDecoration(
      borderRadius: BorderRadius.circular(28),
      border: Border.all(color: Theme.of(context).colorScheme.outlineVariant),
      gradient: LinearGradient(
        begin: Alignment.topLeft,
        end: Alignment.bottomRight,
        colors: [
          Color.alphaBlend(
            Colors.teal.withValues(alpha: .06),
            Theme.of(context).colorScheme.surface,
          ),
          Theme.of(context).colorScheme.surface,
        ],
      ),
    ),
    child: widget.dashboard && configured
        ? Tooltip(
            message:
                error ??
                '${reading?['freshness'] == 'recent' ? 'Cloud updated' : 'Last cloud reading'}: ${observedTime(context)}',
            child: DeyeEnergyOverview(reading: reading, compact: true),
          )
        : Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              Wrap(
                alignment: WrapAlignment.spaceBetween,
                crossAxisAlignment: WrapCrossAlignment.center,
                spacing: 16,
                runSpacing: 12,
                children: [
                  Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      if (!widget.dashboard)
                        const Text(
                          'SOLAR & STORAGE',
                          style: TextStyle(
                            fontSize: 10,
                            letterSpacing: 1.7,
                            fontWeight: FontWeight.w600,
                          ),
                        ),
                      if (!widget.dashboard) const SizedBox(height: 5),
                      Text(
                        'Deye Solar',
                        style: TextStyle(
                          fontSize: widget.dashboard ? 21 : 26,
                          fontWeight: FontWeight.w700,
                        ),
                      ),
                    ],
                  ),
                  Wrap(
                    crossAxisAlignment: WrapCrossAlignment.center,
                    children: [
                      if (!widget.dashboard && canEdit)
                        TextButton.icon(
                          onPressed: () => showDialog(
                            context: context,
                            builder: (_) => DeyeSharing(api: widget.api),
                          ),
                          icon: const Icon(Icons.visibility_outlined),
                          label: const Text('Show solar readings'),
                        ),
                      if (configured && !editing)
                        IconButton(
                          onPressed: busy ? null : refresh,
                          tooltip: 'Refresh energy readings',
                          icon: const Icon(Icons.refresh),
                        ),
                      if (!widget.dashboard && configured && canEdit)
                        TextButton(
                          onPressed: busy
                              ? null
                              : () {
                                  timer?.cancel();
                                  setState(() => editing = !editing);
                                  schedule();
                                },
                          child: const Text('Connection'),
                        ),
                      if (!widget.dashboard && configured && canDelete)
                        IconButton(
                          onPressed: busy ? null : disconnect,
                          tooltip: 'Disconnect Deye Cloud',
                          icon: const Icon(Icons.link_off),
                        ),
                    ],
                  ),
                ],
              ),
              const SizedBox(height: 16),
              if (busy && !backgroundRefresh) const LinearProgressIndicator(),
              if (error != null)
                Card(
                  color: Theme.of(context).colorScheme.errorContainer,
                  child: Padding(
                    padding: const EdgeInsets.all(16),
                    child: Text(error!),
                  ),
                ),
              if (error != null && !configured && !busy)
                Align(
                  alignment: AlignmentDirectional.centerStart,
                  child: TextButton.icon(
                    onPressed: load,
                    icon: const Icon(Icons.refresh),
                    label: const Text('Retry connection status'),
                  ),
                ),
              if (editing && canEdit)
                connectionForm()
              else if (!configured && !busy)
                Padding(
                  padding: const EdgeInsets.symmetric(vertical: 20),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Icon(
                        Icons.solar_power_outlined,
                        size: 40,
                        color: Colors.teal,
                      ),
                      const SizedBox(height: 12),
                      const Text(
                        'Your solar energy, at a glance',
                        style: TextStyle(
                          fontSize: 20,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                      const SizedBox(height: 8),
                      Text(
                        canEdit
                            ? 'Connect Deye Cloud to see solar production, battery charge, load and grid power here.'
                            : 'The owner has not connected Deye Solar yet. Shared readings will appear after the owner configures it.',
                      ),
                      if (widget.dashboard &&
                          canEdit &&
                          widget.onOpen != null) ...[
                        const SizedBox(height: 16),
                        FilledButton.icon(
                          onPressed: widget.onOpen,
                          icon: const Icon(Icons.link),
                          label: const Text('Connect Deye Cloud'),
                        ),
                      ],
                    ],
                  ),
                )
              else if (configured && !editing) ...[
                if (!widget.dashboard) const SizedBox(height: 16),
                if (!widget.dashboard && stations.isNotEmpty)
                  DropdownButtonFormField<String>(
                    key: ValueKey(stationId),
                    initialValue: stationId,
                    isExpanded: true,
                    decoration: InputDecoration(
                      labelText: 'Power station',
                      isDense: widget.dashboard,
                      contentPadding: widget.dashboard
                          ? const EdgeInsets.symmetric(
                              horizontal: 12,
                              vertical: 9,
                            )
                          : null,
                      border: const OutlineInputBorder(),
                    ),
                    items: stations
                        .map(
                          (s) => DropdownMenuItem<String>(
                            value: s['id'],
                            child: Text(
                              s['name'],
                              overflow: TextOverflow.ellipsis,
                            ),
                          ),
                        )
                        .toList(),
                    onChanged: busy
                        ? null
                        : (value) {
                            setState(() {
                              stationId = value;
                              reading = null;
                            });
                            refresh();
                          },
                  ),
                if (stations.isEmpty && !busy)
                  const Text(
                    'No stations were returned. Check the selected Deye region and account permissions.',
                  ),
                if (!widget.dashboard && stations.isNotEmpty) ...[
                  const SizedBox(height: 10),
                  Text(
                    dashboardStation == null
                        ? 'Dashboard station: first available station (automatic)'
                        : 'Dashboard station: ${dashboardStation!['name']}',
                    style: const TextStyle(fontSize: 12),
                  ),
                  if (canEdit)
                    Wrap(
                      spacing: 8,
                      runSpacing: 4,
                      children: [
                        OutlinedButton.icon(
                          onPressed:
                              busy || stationId == dashboardStation?['id']
                              ? null
                              : saveDashboardStation,
                          icon: const Icon(Icons.push_pin_outlined, size: 16),
                          label: Text(
                            stationId == dashboardStation?['id']
                                ? 'Shown on dashboard'
                                : 'Show this station on dashboard',
                          ),
                        ),
                        if (dashboardStation != null)
                          TextButton(
                            onPressed: busy
                                ? null
                                : () => saveDashboardStation(automatic: true),
                            child: const Text(
                              'Use first station automatically',
                            ),
                          ),
                      ],
                    ),
                ],
                if (!widget.dashboard)
                  Row(
                    children: [
                      Expanded(
                        child: Text(
                          total > 50 || page > 1
                              ? 'Station page $page · $total stations'
                              : '$total ${total == 1 ? 'station' : 'stations'}',
                        ),
                      ),
                      if (total > 50 || page > 1)
                        IconButton(
                          onPressed: busy || page == 1
                              ? null
                              : () {
                                  page--;
                                  refresh(inventory: true);
                                },
                          icon: const Icon(Icons.chevron_left),
                          tooltip: 'Previous stations',
                        ),
                      if (total > 50 || page > 1)
                        IconButton(
                          onPressed: busy || page * 50 >= total
                              ? null
                              : () {
                                  page++;
                                  refresh(inventory: true);
                                },
                          icon: const Icon(Icons.chevron_right),
                          tooltip: 'Next stations',
                        ),
                      IconButton(
                        onPressed: busy ? null : () => refresh(inventory: true),
                        icon: const Icon(Icons.sync),
                        tooltip: 'Refresh stations',
                      ),
                    ],
                  ),
                if (stationId != null) ...[
                  Wrap(
                    spacing: 16,
                    runSpacing: 8,
                    crossAxisAlignment: WrapCrossAlignment.center,
                    children: [
                      status(),
                      Text(
                        'Cloud updated: ${observedTime(context)}',
                        style: TextStyle(
                          fontSize: 12,
                          color: Theme.of(context).colorScheme.onSurfaceVariant,
                        ),
                      ),
                    ],
                  ),
                  if (!widget.dashboard) ...[
                    const SizedBox(height: 20),
                    DeyeEnergyOverview(reading: reading),
                    const SizedBox(height: 16),
                    Text(
                      'Live updates without reloading this view. AirLink checks Deye Cloud every 5 seconds; the inverter’s upload timing determines when new readings are available.',
                      style: TextStyle(
                        fontSize: 12,
                        color: Theme.of(context).colorScheme.onSurfaceVariant,
                      ),
                    ),
                  ],
                ],
              ],
            ],
          ),
  );
}
