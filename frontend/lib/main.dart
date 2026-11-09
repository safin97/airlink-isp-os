import 'app_theme.dart';
import 'device_login_profiles.dart';
import 'snmp_visibility_control.dart';
import 'app_language.dart';
import 'dart:async';
import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:latlong2/latlong.dart' show LatLng;
import 'api.dart';
import 'branding.dart';
import 'dashboard_clock.dart';
import 'update_center.dart';
import 'noc_screen.dart';
import 'tower_discovery.dart';
import 'network_map.dart';
import 'sas4_clients.dart';
import 'sas4_connection.dart';
import 'sas4_reports.dart';
import 'account_panel.dart';
import 'payment_settings.dart';
import 'fullscreen.dart' as fullscreen;
import 'tower_marker.dart';
import 'snmp_profile_dialog.dart';
import 'system_performance.dart';
import 'section_access.dart';
import 'role_management.dart';
import 'wireless_clients_dialog.dart';
import 'device_management_dialog.dart';
import 'ethernet_ports_dialog.dart';
import 'device_downtime_history.dart';
import 'ip_address_sort.dart';
import 'device_api_access_panel.dart';
import 'diagnostics_screen.dart';

Color get navy => themeColor(0xff071426, 0xfff2f5fa);
Color get panel => themeColor(0xff10233d, 0xffffffff);
Color get blue => themeColor(0xff438fff, 0xff2455ca);
Color get muted => themeColor(0xff99acc6, 0xff52627a);
Color get green => themeColor(0xff34d399, 0xff087f5b);
Color get red => themeColor(0xffff7385, 0xffbb253e);
Color get orange => themeColor(0xffffb454, 0xff995000);

void main() => runApp(const AirLinkApp());

class AirLinkApp extends StatelessWidget {
  const AirLinkApp({super.key, this.home = const SessionGate()});
  final Widget home;
  @override
  Widget build(BuildContext context) => ValueListenableBuilder<AppLanguage>(
    valueListenable: appLanguage,
    builder: (context, language, child) => ValueListenableBuilder<ThemeMode>(
      valueListenable: appThemeMode,
      builder: (context, mode, child) => MaterialApp(
        // Badini uses Arabic Material controls; application copy is Badini.
        locale: Locale(language.rtl ? 'ar' : 'en'),
        supportedLocales: const [Locale('en'), Locale('ar')],
        localizationsDelegates: GlobalMaterialLocalizations.delegates,
        builder: (context, child) => Directionality(
          textDirection: language.rtl ? TextDirection.rtl : TextDirection.ltr,
          child: child!,
        ),
        title: 'AirLink ISP OS',
        debugShowCheckedModeBanner: false,
        theme: airLinkTheme(Brightness.light),
        darkTheme: airLinkTheme(Brightness.dark),
        themeMode: mode,
        home: home,
      ),
    ),
  );
}

class SessionGate extends StatefulWidget {
  const SessionGate({super.key});
  @override
  State<SessionGate> createState() => _SessionGateState();
}

class _SessionGateState extends State<SessionGate> with LanguageRebuild {
  final api = Api();
  bool loading = true;
  bool initialized = true;
  String? error;
  @override
  void initState() {
    super.initState();
    restore();
  }

  Future<void> restore() async {
    try {
      initialized = (await api.request('/setup/status'))['initialized'];
      if (initialized) {
        try {
          await api.refresh();
        } on ApiException catch (e) {
          if (e.status != 401) rethrow;
        }
      }
    } catch (e) {
      error = e.toString();
    }
    if (mounted) setState(() => loading = false);
  }

  @override
  Widget build(BuildContext context) {
    if (loading) {
      return const Scaffold(
        body: Center(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              AirLinkLogo(width: 280),
              SizedBox(height: 24),
              CircularProgressIndicator(),
            ],
          ),
        ),
      );
    }
    if (error != null) {
      return Scaffold(
        body: Center(
          child: SizedBox(
            width: 480,
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                const AirLinkLogo(width: 280),
                const SizedBox(height: 20),
                Icon(Icons.cloud_off, size: 32, color: orange),
                const SizedBox(height: 20),
                const AppText('AirLink server is unavailable'),
                Padding(padding: const EdgeInsets.all(20), child: Text(error!)),
                FilledButton(
                  onPressed: () {
                    setState(() {
                      error = null;
                      loading = true;
                    });
                    restore();
                  },
                  child: const AppText('Retry'),
                ),
              ],
            ),
          ),
        ),
      );
    }
    if (api.user == null) {
      return LoginView(
        api: api,
        initialized: initialized,
        done: () => setState(() => initialized = true),
      );
    }
    return Operations(
      api: api,
      logout: () async {
        await api.logout();
        if (mounted) setState(() {});
      },
    );
  }
}

class LoginView extends StatefulWidget {
  final Api api;
  final bool initialized;
  final VoidCallback done;
  const LoginView({
    super.key,
    required this.api,
    required this.initialized,
    required this.done,
  });
  @override
  State<LoginView> createState() => _LoginViewState();
}

class _LoginViewState extends State<LoginView> with LanguageRebuild {
  final username = TextEditingController();
  final password = TextEditingController();
  final confirm = TextEditingController();
  final setupToken = TextEditingController();
  bool busy = false;
  String? error;
  @override
  void dispose() {
    for (final c in [username, password, confirm, setupToken]) {
      c.dispose();
    }
    super.dispose();
  }

  Future<void> submit() async {
    setState(() {
      busy = true;
      error = null;
    });
    try {
      if (!widget.initialized) {
        await widget.api.request(
          '/setup',
          method: 'POST',
          body: {
            'username': username.text.trim(),
            'password': password.text,
            'confirm_password': confirm.text,
            'token': setupToken.text.trim(),
          },
        );
      }
      await widget.api.login(username.text.trim(), password.text);
      widget.done();
    } catch (e) {
      if (mounted) setState(() => error = e.toString());
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
    appBar: PreferredSize(
      preferredSize: const Size.fromHeight(kToolbarHeight),
      child: Directionality(
        textDirection: TextDirection.ltr,
        child: AppBar(
          automaticallyImplyLeading: false,
          actions: const [
            ThemeToggle(),
            LanguageSelector(),
            SizedBox(width: 12),
          ],
        ),
      ),
    ),
    body: Center(
      child: SingleChildScrollView(
        padding: const EdgeInsets.all(24),
        child: SizedBox(
          width: 440,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              const Center(child: AirLinkLogo(width: 156, stacked: true)),
              const SizedBox(height: 24),
              const AppText(
                'AirLink ISP OS',
                textAlign: TextAlign.center,
                style: TextStyle(fontSize: 24, fontWeight: FontWeight.w700),
              ),
              const SizedBox(height: 8),
              AppText(
                'NETWORK OPERATIONS',
                textAlign: TextAlign.center,
                style: TextStyle(color: muted, letterSpacing: 3),
              ),
              const SizedBox(height: 40),
              AppText(
                widget.initialized
                    ? 'Sign in to your network'
                    : 'Create the first owner',
                style: const TextStyle(fontSize: 22),
              ),
              const SizedBox(height: 24),
              TextField(
                controller: username,
                decoration: InputDecoration(labelText: tr('Username')),
                autofillHints: const [AutofillHints.username],
              ),
              const SizedBox(height: 16),
              TextField(
                controller: password,
                obscureText: true,
                decoration: InputDecoration(labelText: tr('Password')),
                onSubmitted: (_) => busy ? null : submit(),
              ),
              if (!widget.initialized) ...[
                const SizedBox(height: 16),
                TextField(
                  controller: confirm,
                  obscureText: true,
                  decoration: InputDecoration(
                    labelText: tr('Confirm password'),
                  ),
                ),
                const SizedBox(height: 16),
                TextField(
                  controller: setupToken,
                  obscureText: true,
                  decoration: InputDecoration(
                    labelText: tr('Local setup token'),
                  ),
                ),
                Padding(
                  padding: EdgeInsets.symmetric(vertical: 16),
                  child: AppText(
                    'Complete setup on the server console, or enter its local setup token. Use at least 14 password characters.',
                    style: TextStyle(color: muted),
                  ),
                ),
              ],
              if (error != null)
                Padding(
                  padding: const EdgeInsets.symmetric(vertical: 16),
                  child: Text(error!, style: TextStyle(color: red)),
                ),
              const SizedBox(height: 24),
              FilledButton(
                onPressed: busy ? null : submit,
                child: AppText(
                  busy
                      ? 'Connecting…'
                      : widget.initialized
                      ? 'Sign in'
                      : 'Create owner',
                ),
              ),
              const SizedBox(height: 24),
              AppText(
                'Secure access • Your network, under your control',
                textAlign: TextAlign.center,
                style: TextStyle(color: muted),
              ),
            ],
          ),
        ),
      ),
    ),
  );
}

const pages = [
  'Dashboard',
  'NOC Screen',
  'Towers',
  'ISP Card',
  'Managers',
  'Access Roles',
  'Monitoring',
  'Network Map',
  'Alerts',
  'Reports',
  'Software Updates',
  'Settings',
  'Diagnostics',
  'My account',
  'Device login',
  'Towers API',
];
const icons = [
  Icons.space_dashboard_outlined,
  Icons.desktop_windows_outlined,
  Icons.cell_tower,
  Icons.devices,
  Icons.group_outlined,
  Icons.admin_panel_settings_outlined,
  Icons.monitor_heart_outlined,
  Icons.map_outlined,
  Icons.notifications_outlined,
  Icons.assessment_outlined,
  Icons.system_update_alt,
  Icons.settings_outlined,
  Icons.health_and_safety_outlined,
  Icons.account_circle_outlined,
  Icons.password_outlined,
  Icons.key_outlined,
];

class Operations extends StatefulWidget {
  final Api api;
  final Future<void> Function() logout;
  const Operations({super.key, required this.api, required this.logout});
  @override
  State<Operations> createState() => _OperationsState();
}

class _OperationsState extends State<Operations> with LanguageRebuild {
  int page = 0;
  int accountRevision = 0;
  String accountPage = 'Account profile';
  String? settingsPage;
  bool ispDashboard = true;
  bool ispReports = false;
  bool ispOnline = false;
  bool nocExpanded = false;
  void Function()? stopFullscreen;
  bool mapExpanded = false;
  bool loading = true;
  bool refreshing = false;
  String? error;
  String search = '';
  String? towerFilter;
  String? placeFilter;
  int towerOrigin = pages.indexOf('Towers');
  DateTime? observed;
  Map<String, dynamic> summary = {};
  Map<String, List<dynamic>> rows = {};
  List<dynamic> samples = [];
  String? deviceId;
  StreamSubscription<Map<String, dynamic>>? liveSubscription;
  bool liveConnected = false;
  Api get api => widget.api;
  String get role => api.user!['role'];
  bool get owner => role == 'owner';
  bool get writer => owner || usesSectionPermissions(api.user!);
  bool get canViewSas4Connection =>
      writer &&
      (hasSection(api.user!, 'isp_card') || hasSection(api.user!, 'noc'));
  Map<String, IconData> get accountPages => accountPagesFor(api.user!);
  bool get inventoryWriter => canEditSection(api.user!, 'towers');
  bool get inventoryDeleter => canDeleteSection(api.user!, 'towers');
  bool get towerDeleter =>
      inventoryDeleter &&
      (owner ||
          api.user!['access_role_id'] != null ||
          api.user!['manager_role_id'] != null ||
          api.user!['access_policy_configured'] == true);
  bool get canManageSettings =>
      owner ||
      (usesSectionPermissions(api.user!) && hasSection(api.user!, 'settings'));
  bool get canManageUpdates =>
      owner ||
      (usesSectionPermissions(api.user!) &&
          hasSection(api.user!, 'software_updates'));
  bool canPage(int index) => pages[index] == 'My account'
      ? true
      : pages[index] == 'Diagnostics'
      ? owner ||
            (usesSectionPermissions(api.user!) &&
                hasSection(api.user!, 'settings'))
      : pages[index] == 'Towers API'
      ? owner
      : pages[index] == 'Device login'
      ? owner
      : (pages[index] == 'Settings' && canViewSnmpProfiles(api.user!)) ||
            hasSection(
              api.user!,
              pageSections.entries
                  .firstWhere((entry) => entry.value == pages[index])
                  .key,
            );

  void selectAllowedPage() {
    if (!accountPages.containsKey(accountPage)) {
      accountPage = accountPages.keys.first;
    }
    if (canPage(page)) return;
    if (nocExpanded) unawaited(fullscreen.leaveFullscreen());
    page =
        List.generate(pages.length, (i) => i).where(canPage).firstOrNull ?? 0;
    towerFilter = null;
    placeFilter = null;
    nocExpanded = false;
    mapExpanded = false;
  }

  @override
  void initState() {
    super.initState();
    selectAllowedPage();
    stopFullscreen = fullscreen.watchFullscreen(
      changed: (active) {
        if (!active && mounted && nocExpanded) {
          setState(() => nocExpanded = false);
        }
      },
      nocActive: () => mounted && pages[page] == 'NOC Screen',
      toggle: toggleNoc,
    );
    liveSubscription = api.liveEvents.listen(applyLive);
    unawaited(
      reload().then((_) {
        if (mounted) api.startLive();
      }),
    );
  }

  @override
  void dispose() {
    liveSubscription?.cancel();
    api.stopLive();
    stopFullscreen?.call();
    if (nocExpanded) unawaited(fullscreen.leaveFullscreen());
    super.dispose();
  }

  void applyLive(Map<String, dynamic> event) {
    if (!mounted) return;
    if (event['type'] == 'session_expired') {
      unawaited(widget.logout());
      return;
    }
    if (event['type'] == 'connection') {
      if (liveConnected) setState(() => liveConnected = false);
      return;
    }
    if (event['type'] == 'heartbeat') {
      if (!liveConnected) setState(() => liveConnected = true);
      return;
    }
    final identity = event['user'];
    final updates = event['rows'] as Map? ?? {};
    // Keep performance data current without rebuilding unrelated forms, lists or maps.
    if (event['type'] == 'patch' &&
        identity == null &&
        updates.isEmpty &&
        event.containsKey('summary') &&
        liveConnected &&
        error == null &&
        observed != null &&
        !['Dashboard', 'NOC Screen'].contains(pages[page])) {
      summary = Map<String, dynamic>.from(event['summary']);
      observed = DateTime.now();
      return;
    }
    setState(() {
      liveConnected = true;
      if (identity is Map) {
        api.user = Map<String, dynamic>.from(identity);
        selectAllowedPage();
      }
      if (event.containsKey('summary')) {
        summary = Map<String, dynamic>.from(event['summary']);
      }
      if (event['type'] == 'snapshot') rows = {};
      for (final key in updates.keys) {
        rows[key as String] = List<dynamic>.from(updates[key]);
      }
      if (placeFilter != null &&
          placeFilter != '' &&
          !list('places').any((p) => p['id'] == placeFilter)) {
        placeFilter = null;
      }
      if (towerFilter != null &&
          !list('towers').any((t) => t['id'] == towerFilter)) {
        towerFilter = null;
      }
      if (deviceId != null &&
          !list('devices').any((d) => d['id'] == deviceId)) {
        deviceId = null;
        samples = [];
      }
      observed = DateTime.now();
      error = null;
    });
    if (deviceId != null && updates.containsKey('devices')) {
      unawaited(loadMetrics(deviceId!, quiet: true));
    }
  }

  void toggleNoc() {
    setState(() => nocExpanded = !nocExpanded);
    if (nocExpanded) {
      unawaited(fullscreen.enterFullscreen());
    } else {
      unawaited(fullscreen.leaveFullscreen());
    }
  }

  void toast(String text) {
    if (mounted) {
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(text)));
    }
  }

  Future<void> reload({bool quiet = false}) async {
    if (refreshing) return;
    refreshing = true;
    if (!quiet) setState(() => loading = true);
    try {
      if (!owner) {
        final identity = await api.request('/auth/me');
        if (!mounted) return;
        if (identity is Map &&
            identity['role'] != null &&
            jsonEncode(identity) != jsonEncode(api.user)) {
          setState(() {
            api.user = Map<String, dynamic>.from(identity);
            rows = {};
            summary = {};
            samples = [];
            deviceId = null;
            selectAllowedPage();
          });
        }
      }
      final names = [
        'towers',
        'places',
        'sectors',
        'devices',
        'alerts',
        'links',
        if (owner) ...['users', 'access-roles'],
        if (canViewSnmpProfiles(api.user!)) 'snmp-profiles',
      ].where((resource) => canReadResource(api.user!, resource)).toList();
      final data = await Future.wait([
        canReadResource(api.user!, 'dashboard')
            ? api.request('/dashboard')
            : Future<dynamic>.value(<String, dynamic>{}),
        ...names.map((x) => api.request('/$x')),
      ]);
      final next = <String, List<dynamic>>{};
      for (var i = 0; i < names.length; i++) {
        next[names[i]] = data[i + 1] as List<dynamic>;
      }
      if (!mounted) return;
      final nextSummary = Map<String, dynamic>.from(data.first);
      final summaryChanged =
          jsonEncode(
            Map<String, dynamic>.from(summary)..remove('observed_at'),
          ) !=
          jsonEncode(
            Map<String, dynamic>.from(nextSummary)..remove('observed_at'),
          );
      final rowsChanged = jsonEncode(rows) != jsonEncode(next);
      if (!quiet || summaryChanged || rowsChanged || error != null) {
        setState(() {
          if (summaryChanged) summary = nextSummary;
          if (rowsChanged) rows = next;
          if (placeFilter != null &&
              placeFilter != '' &&
              !list('places').any((p) => p['id'] == placeFilter)) {
            placeFilter = null;
          }
          observed = DateTime.now();
          error = null;
        });
      }
      if (deviceId != null && list('devices').any((d) => d['id'] == deviceId)) {
        await loadMetrics(deviceId!, quiet: quiet);
      }
    } catch (e) {
      if (mounted && error != e.toString()) {
        setState(() => error = e.toString());
      }
    } finally {
      refreshing = false;
      if (mounted && loading) setState(() => loading = false);
    }
  }

  List<dynamic> list(String key) => rows[key] ?? [];
  List<dynamic> filtered(String key) => list(key)
      .where(
        (x) =>
            key != 'devices' ||
            towerFilter == null ||
            x['tower_id'] == towerFilter,
      )
      .where((x) => jsonEncode(x).toLowerCase().contains(search.toLowerCase()))
      .toList();
  String nameOf(String key, dynamic id) =>
      list(key)
          .where((x) => x['id'] == id)
          .map((x) => (x['name'] ?? x['username']).toString())
          .firstOrNull ??
      (id?.toString() ?? '—');
  Future<void> loadMetrics(String id, {bool quiet = false}) async {
    if (!hasSection(api.user!, 'monitoring')) return;
    try {
      final data = await api.request('/devices/$id/metrics');
      if (mounted &&
          (!quiet || deviceId == id) &&
          (deviceId != id || jsonEncode(samples) != jsonEncode(data))) {
        setState(() {
          deviceId = id;
          samples = data;
        });
      }
    } catch (e) {
      if (!quiet) toast(e.toString());
    }
  }

  Future<void> openSas4Connection() async {
    if (!canViewSas4Connection) return;
    await showDialog<void>(
      context: context,
      barrierDismissible: false,
      builder: (dialogContext) => AlertDialog(
        content: SizedBox(
          width: 520,
          child: SingleChildScrollView(child: Sas4Connection(api: api)),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext),
            child: const AppText('Done'),
          ),
        ],
      ),
    );
    if (mounted) setState(() => accountRevision++);
  }

  void navigate(int index) {
    if (!canPage(index)) return;
    if (nocExpanded) unawaited(fullscreen.leaveFullscreen());
    setState(() {
      page = index;
      settingsPage = null;
      if (pages[index] == 'My account') accountPage = accountPages.keys.first;
      mapExpanded = pages[index] == 'Network Map';
      nocExpanded = false;
      search = '';
      towerFilter = null;
      placeFilter = null;
    });
  }

  void openTowerDevices(String id) {
    if (!hasSection(api.user!, 'towers')) return;
    if (nocExpanded) unawaited(fullscreen.leaveFullscreen());
    setState(() {
      towerOrigin = page;
      page = pages.indexOf('Towers');
      towerFilter = id;
      search = '';
      nocExpanded = false;
    });
  }

  Widget navigation() => SizedBox(
    width: 244,
    child: Material(
      color: themeColor(0xff091a30, 0xffe8eef8),
      child: SafeArea(
        child: Column(
          children: [
            Padding(
              padding: EdgeInsets.fromLTRB(24, 24, 24, 20),
              child: Column(
                children: [
                  AirLinkLogo(),
                  SizedBox(height: 12),
                  AppText(
                    'ISP OPERATING SYSTEM',
                    style: TextStyle(
                      fontSize: 9,
                      color: muted,
                      letterSpacing: 1.7,
                    ),
                  ),
                ],
              ),
            ),
            Expanded(
              child: ListView.builder(
                itemCount: pages.length,
                itemBuilder: (context, i) =>
                    !canPage(i) && pages[i] != 'Settings'
                    ? const SizedBox.shrink()
                    : Padding(
                        padding: const EdgeInsets.symmetric(
                          horizontal: 12,
                          vertical: 3,
                        ),
                        child: Column(
                          children: [
                            if (canPage(i))
                              ListTile(
                                dense: true,
                                selected: i == page,
                                selectedTileColor: blue.withValues(alpha: .15),
                                selectedColor: blue,
                                shape: RoundedRectangleBorder(
                                  borderRadius: BorderRadius.circular(10),
                                ),
                                leading: Icon(icons[i], size: 22),
                                title: AppText(pages[i]),
                                onTap: () {
                                  navigate(i);
                                  if (Scaffold.of(context).isDrawerOpen) {
                                    Navigator.pop(context);
                                  }
                                },
                              ),
                            if (pages[i] == 'Settings' &&
                                page == i &&
                                canPage(i))
                              for (final entry in settingsPages.entries)
                                Padding(
                                  padding: const EdgeInsets.only(
                                    left: 24,
                                    top: 3,
                                  ),
                                  child: ListTile(
                                    dense: true,
                                    selected: settingsPage == entry.key,
                                    selectedColor: blue,
                                    selectedTileColor: blue.withValues(
                                      alpha: .15,
                                    ),
                                    leading: Icon(entry.value, size: 18),
                                    title: AppText(entry.key),
                                    onTap: () {
                                      setState(() => settingsPage = entry.key);
                                      if (Scaffold.of(context).isDrawerOpen) {
                                        Navigator.pop(context);
                                      }
                                    },
                                  ),
                                ),
                            if (pages[i] == 'My account' && page == i)
                              for (final entry in accountPages.entries)
                                Padding(
                                  padding: const EdgeInsets.only(
                                    left: 24,
                                    top: 3,
                                  ),
                                  child: ListTile(
                                    dense: true,
                                    selected: accountPage == entry.key,
                                    selectedColor: blue,
                                    selectedTileColor: blue.withValues(
                                      alpha: .15,
                                    ),
                                    shape: RoundedRectangleBorder(
                                      borderRadius: BorderRadius.circular(10),
                                    ),
                                    leading: Icon(entry.value, size: 18),
                                    title: AppText(entry.key),
                                    onTap: () {
                                      setState(() => accountPage = entry.key);
                                      if (Scaffold.of(context).isDrawerOpen) {
                                        Navigator.pop(context);
                                      }
                                    },
                                  ),
                                ),
                            if (pages[i] == 'Settings' && canViewSas4Connection)
                              ListTile(
                                dense: true,
                                leading: const Icon(Icons.link, size: 22),
                                title: const AppText('SAS4 connection'),
                                onTap: () {
                                  if (Scaffold.of(context).isDrawerOpen) {
                                    Navigator.pop(context);
                                  }
                                  openSas4Connection();
                                },
                              ),
                            if (pages[i] == 'ISP Card' && page == i)
                              for (final dashboard in [true, false])
                                Padding(
                                  padding: const EdgeInsets.only(
                                    left: 24,
                                    top: 3,
                                  ),
                                  child: ListTile(
                                    dense: true,
                                    selected:
                                        !ispReports &&
                                        ispDashboard == dashboard,
                                    selectedColor: blue,
                                    selectedTileColor: blue.withValues(
                                      alpha: .15,
                                    ),
                                    shape: RoundedRectangleBorder(
                                      borderRadius: BorderRadius.circular(10),
                                    ),
                                    leading: Icon(
                                      dashboard
                                          ? Icons.space_dashboard_outlined
                                          : Icons.people_outline,
                                      size: 18,
                                    ),
                                    title: AppText(
                                      dashboard ? 'Dashboard' : 'Users',
                                    ),
                                    onTap: () {
                                      setState(() {
                                        ispReports = false;
                                        ispDashboard = dashboard;
                                      });
                                      if (Scaffold.of(context).isDrawerOpen) {
                                        Navigator.pop(context);
                                      }
                                    },
                                  ),
                                ),
                            if (pages[i] == 'ISP Card' &&
                                page == i &&
                                !ispDashboard &&
                                !ispReports)
                              for (final online in [false, true])
                                Padding(
                                  padding: const EdgeInsets.only(
                                    left: 40,
                                    top: 3,
                                  ),
                                  child: ListTile(
                                    dense: true,
                                    contentPadding: const EdgeInsets.symmetric(
                                      horizontal: 12,
                                    ),
                                    selected: ispOnline == online,
                                    selectedColor: blue,
                                    selectedTileColor: blue.withValues(
                                      alpha: .15,
                                    ),
                                    shape: RoundedRectangleBorder(
                                      borderRadius: BorderRadius.circular(10),
                                    ),
                                    leading: Icon(
                                      online ? Icons.wifi : Icons.list_alt,
                                      size: 16,
                                    ),
                                    title: AppText(
                                      online ? 'Online users' : 'Users list',
                                      style: const TextStyle(fontSize: 13),
                                    ),
                                    onTap: () {
                                      setState(() => ispOnline = online);
                                      if (Scaffold.of(context).isDrawerOpen) {
                                        Navigator.pop(context);
                                      }
                                    },
                                  ),
                                ),
                            if (pages[i] == 'ISP Card' && page == i)
                              Padding(
                                padding: const EdgeInsets.only(
                                  left: 24,
                                  top: 3,
                                ),
                                child: ListTile(
                                  key: const ValueKey('isp-card-reports'),
                                  dense: true,
                                  selected: ispReports,
                                  selectedColor: blue,
                                  selectedTileColor: blue.withValues(
                                    alpha: .15,
                                  ),
                                  leading: const Icon(
                                    Icons.receipt_long_outlined,
                                    size: 18,
                                  ),
                                  title: const AppText('Reports'),
                                  onTap: () {
                                    setState(() => ispReports = true);
                                    if (Scaffold.of(context).isDrawerOpen) {
                                      Navigator.pop(context);
                                    }
                                  },
                                ),
                              ),
                          ],
                        ),
                      ),
              ),
            ),
            Divider(color: themeColor(0xff20334e, 0xffd6dfeb)),
            ListTile(
              leading: const CircleAvatar(child: Icon(Icons.person_outline)),
              title: Text(api.user!['username']),
              subtitle: Text(role, style: TextStyle(color: muted)),
              trailing: IconButton(
                tooltip: 'Sign out',
                icon: const Icon(Icons.logout, size: 20),
                onPressed: widget.logout,
              ),
            ),
            const SizedBox(height: 12),
          ],
        ),
      ),
    ),
  );
  @override
  Widget build(BuildContext context) => LayoutBuilder(
    builder: (context, constraints) {
      final wide = constraints.maxWidth >= 1050;
      final mapFull = pages[page] == 'Network Map' && mapExpanded;
      return Scaffold(
        drawer: nocExpanded || (wide && !mapFull)
            ? null
            : Drawer(child: navigation()),
        body: Row(
          children: [
            if (wide && !nocExpanded && !mapFull) navigation(),
            Expanded(
              child: Column(
                children: [
                  if (!nocExpanded)
                    Container(
                      padding: EdgeInsets.symmetric(
                        horizontal: wide ? 24 : 12,
                        vertical: 18,
                      ),
                      decoration: BoxDecoration(
                        border: Border(
                          bottom: BorderSide(
                            color: themeColor(0xff20334e, 0xffd6dfeb),
                          ),
                        ),
                      ),
                      child: Row(
                        textDirection: TextDirection.ltr,
                        children: [
                          if (!wide || mapFull)
                            Builder(
                              builder: (context) => IconButton(
                                icon: const Icon(Icons.menu),
                                onPressed: () =>
                                    Scaffold.of(context).openDrawer(),
                              ),
                            ),
                          if (constraints.maxWidth >= 600 &&
                              (!wide || nocExpanded || mapFull)) ...[
                            const AirLinkLogo(width: 40, stacked: true),
                            const SizedBox(width: 12),
                          ],
                          Expanded(
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                AppText(
                                  pages[page],
                                  maxLines: 1,
                                  overflow: TextOverflow.ellipsis,
                                  style: const TextStyle(
                                    fontSize: 25,
                                    fontWeight: FontWeight.w600,
                                  ),
                                ),
                                Text(
                                  observed == null
                                      ? 'Connecting to your network'
                                      : '${tr('Updated')} ${TimeOfDay.fromDateTime(observed!).format(context)} • ${tr(liveConnected ? 'Live' : 'Reconnecting…')}',
                                  style: TextStyle(color: muted, fontSize: 12),
                                ),
                                if (constraints.maxWidth < 750)
                                  const DashboardClock(compact: true),
                              ],
                            ),
                          ),
                          if (constraints.maxWidth >= 750) ...[
                            const DashboardClock(),
                            const SizedBox(width: 16),
                          ],
                          const ThemeToggle(),
                          const LanguageSelector(),
                        ],
                      ),
                    ),
                  if (error != null)
                    Container(
                      width: double.infinity,
                      color: red.withValues(alpha: .15),
                      padding: const EdgeInsets.all(12),
                      child: Text(
                        'Refresh failed — previous data may be stale. $error',
                        style: TextStyle(color: red),
                      ),
                    ),
                  if (loading) const LinearProgressIndicator(minHeight: 2),
                  Expanded(
                    child: pages[page] == 'Network Map' && canPage(page)
                        ? networkMap()
                        : SingleChildScrollView(
                            padding: EdgeInsets.all(wide ? 28 : 16),
                            child: content(),
                          ),
                  ),
                ],
              ),
            ),
          ],
        ),
      );
    },
  );
  Widget content() {
    if (!canPage(page)) {
      return notice(
        'No sections assigned',
        'The owner can enable sections for your account. My account is still available.',
      );
    }
    switch (pages[page]) {
      case 'Dashboard':
        return dashboard();
      case 'NOC Screen':
        return NocScreen(
          summary: summary,
          towers: list('towers'),
          devices: list('devices'),
          alerts: list('alerts'),
          hasData: observed != null,
          expanded: nocExpanded,
          toggleExpanded: toggleNoc,
          openAlerts: () => navigate(pages.indexOf('Alerts')),
          openMonitoring: () => navigate(pages.indexOf('Monitoring')),
          openTowerDevices: openTowerDevices,
        );
      case 'Towers':
        return towerFilter != null ? inventory('devices') : towersView();
      case 'ISP Card':
        return clients();
      case 'My account':
        return AccountPanel(
          key: ValueKey('account-$accountPage-$accountRevision'),
          api: api,
          page: accountPage,
        );
      case 'Towers API':
        return DeviceLoginProfiles(
          key: const ValueKey('towers-api'),
          api: api,
          towers: true,
        );
      case 'Device login':
        return DeviceLoginProfiles(api: api);
      case 'Managers':
        return owner
            ? inventory('users')
            : notice(
                'Owner access required',
                'Account creation and assignments are restricted to the owner.',
              );
      case 'Access Roles':
        return RoleManagement(
          key: ValueKey(pages[page]),
          api: api,
          accessGroups: true,
          onChanged: () => reload(quiet: true),
        );
      case 'Monitoring':
        return monitoring();
      case 'Network Map':
        return networkMap();
      case 'Alerts':
        return alertsView();
      case 'Reports':
        return reports();
      case 'Software Updates':
        return canManageUpdates
            ? updates()
            : notice(
                'Owner access required',
                'Software Updates access must be enabled by the owner.',
              );
      case 'Diagnostics':
        return DiagnosticsScreen(api: api);
      default:
        return settings();
    }
  }

  Widget card(Widget child) => Card(
    margin: EdgeInsets.zero,
    child: Padding(padding: const EdgeInsets.all(22), child: child),
  );
  Widget notice(String title, String detail) => card(
    Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        AppText(
          title,
          style: const TextStyle(fontSize: 20, fontWeight: FontWeight.w600),
        ),
        const SizedBox(height: 12),
        AppText(detail, style: TextStyle(color: muted, height: 1.6)),
      ],
    ),
  );
  Widget section(String title, Widget child, {Widget? action}) => card(
    Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          children: [
            Expanded(
              child: AppText(
                title,
                style: const TextStyle(
                  fontSize: 18,
                  fontWeight: FontWeight.w600,
                ),
              ),
            ),
            if (action != null) action,
          ],
        ),
        const SizedBox(height: 20),
        child,
      ],
    ),
  );
  Widget badge(dynamic status) {
    final color = status == 'online'
        ? green
        : status == 'offline' || status == 'critical'
        ? red
        : status == 'warning'
        ? orange
        : muted;
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Icon(Icons.circle, size: 7, color: color),
        const SizedBox(width: 7),
        Text(
          status?.toString() ?? 'unknown',
          style: TextStyle(color: color, fontSize: 12),
        ),
      ],
    );
  }

  String value(dynamic x, {String suffix = ''}) =>
      x == null ? 'Unavailable' : '$x$suffix';

  Widget wirelessClientCount(Map<String, dynamic> device) {
    final count = device['telemetry']?['wireless_clients'];
    if (count is! num) return const AppText('Unavailable');
    return TextButton(
      key: ValueKey('wireless-clients-${device['id']}'),
      onPressed: () => showDialog<void>(
        context: context,
        builder: (_) => WirelessClientsDialog(api: api, device: device),
      ),
      child: Text(count.toInt().toString()),
    );
  }

  Widget deviceDowntime(Map<String, dynamic> device) {
    final seconds = device['downtime_seconds'];
    if (device['status'] == 'online') return const Text('—');
    if (device['status'] != 'offline' || seconds is! num) {
      return const AppText('Unavailable');
    }
    final duration = seconds.toInt();
    return Tooltip(
      message:
          'Time since the first failed monitoring check'
          '${device['down_since'] == null ? '' : '\nSince: ${device['down_since']}'}',
      child: Text(
        '${duration ~/ 86400}d ${(duration % 86400) ~/ 3600}h ${(duration % 3600) ~/ 60}m',
        style: TextStyle(color: red),
      ),
    );
  }

  Widget deviceReading(Map<String, dynamic> device, String field) {
    final data = Map<String, dynamic>.from(device['telemetry'] ?? {});
    String reading = 'Unavailable';
    String number(num value) => value == value.roundToDouble()
        ? value.toInt().toString()
        : value.toStringAsFixed(1);
    if (field == 'ethernet_links') {
      final links = (data[field] as List? ?? []).whereType<Map>().where(
        (port) => port['name']?.toString().toLowerCase() == 'ether1',
      );
      if (links.isNotEmpty) {
        reading = links
            .map((p) => '${p['name']}: ${number(p['speed_mbps'] as num)} Mbps')
            .join(' · ');
      }
    } else if (field == 'wireless') {
      final names = (data['wireless_ssids'] as List?) ?? [];
      if (names.isNotEmpty) reading = names.join(' · ');
    } else if (field == 'uptime_seconds' && data[field] is num) {
      final seconds = (data[field] as num).toInt();
      reading =
          '${seconds ~/ 86400}d ${(seconds % 86400) ~/ 3600}h ${(seconds % 3600) ~/ 60}m';
    } else if (data[field] is num) {
      reading = '${number(data[field])}%';
    }
    final details = [
      reading,
      if (data['telemetry_source'] != null) data['telemetry_source'],
      if (data['device_model'] != null) data['device_model'],
      if (data['firmware_version'] != null) data['firmware_version'],
      if (device['telemetry_at'] != null)
        'Collected: ${device['telemetry_at']}',
    ].join('\n');
    return Tooltip(
      message: details,
      child: ConstrainedBox(
        constraints: const BoxConstraints(maxWidth: 240),
        child: Text(reading, maxLines: 2, overflow: TextOverflow.ellipsis),
      ),
    );
  }

  Widget dashboard() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        SystemPerformance(
          data: Map<String, dynamic>.from(summary['system'] ?? {}),
        ),
        const SizedBox(height: 24),
        section(
          'Network health',
          Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Wrap(
                spacing: 24,
                runSpacing: 12,
                children: [
                  badge('online'),
                  Text('${summary['online'] ?? 0} devices'),
                  badge('offline'),
                  Text('${summary['offline'] ?? 0} devices'),
                  badge('unknown'),
                  Text('${summary['unknown'] ?? 0} devices'),
                ],
              ),
              const SizedBox(height: 16),
              HealthBar(
                online: (summary['online'] ?? 0) as int,
                offline: (summary['offline'] ?? 0) as int,
                unknown: (summary['unknown'] ?? 0) as int,
              ),
            ],
          ),
        ),
      ],
    );
  }

  Widget towersView() {
    final towers = filtered('towers')
        .where((t) => t['place_id'] == (placeFilter == '' ? null : placeFilter))
        .toList();
    final unassigned = list(
      'towers',
    ).where((t) => t['place_id'] == null).length;
    final places =
        <dynamic>[
              ...list('places'),
              if (unassigned > 0)
                {
                  'id': '',
                  'name': 'Unassigned towers',
                  'tower_count': unassigned,
                },
            ]
            .where(
              (p) => p['name'].toString().toLowerCase().contains(
                search.toLowerCase(),
              ),
            )
            .toList();
    final deviceCounts = <dynamic, int>{};
    final onlineCounts = <dynamic, int>{};
    final offlineCounts = <dynamic, int>{};
    for (final device in list('devices')) {
      deviceCounts.update(
        device['tower_id'],
        (count) => count + 1,
        ifAbsent: () => 1,
      );
      final statusCounts = switch (device['status']) {
        'online' => onlineCounts,
        'offline' => offlineCounts,
        _ => null,
      };
      statusCounts?.update(
        device['tower_id'],
        (count) => count + 1,
        ifAbsent: () => 1,
      );
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        if (placeFilter == null) ...[
          Row(
            children: [
              const Expanded(
                child: AppText(
                  'Places',
                  style: TextStyle(fontSize: 24, fontWeight: FontWeight.w600),
                ),
              ),
              if (owner)
                FilledButton.icon(
                  onPressed: () => edit('places'),
                  icon: const Icon(Icons.add_location_alt_outlined),
                  label: const AppText('Add place'),
                ),
            ],
          ),
          const SizedBox(height: 16),
          toolbar('places'),
          if (places.isNotEmpty)
            Wrap(
              spacing: 12,
              runSpacing: 12,
              children: places
                  .map(
                    (place) => SizedBox(
                      width: 220,
                      height: 150,
                      child: Card(
                        margin: EdgeInsets.zero,
                        child: InkWell(
                          borderRadius: BorderRadius.circular(12),
                          onTap: () => setState(() {
                            placeFilter = place['id'];
                            search = '';
                          }),
                          child: Padding(
                            padding: const EdgeInsets.all(16),
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Row(
                                  children: [
                                    Icon(
                                      Icons.location_on_outlined,
                                      color: blue,
                                    ),
                                    const Spacer(),
                                    if (owner && place['id'] != '')
                                      PopupMenuButton<String>(
                                        tooltip: 'Place actions',
                                        onSelected: (action) {
                                          if (action == 'edit') {
                                            edit(
                                              'places',
                                              existing:
                                                  Map<String, dynamic>.from(
                                                    place,
                                                  ),
                                            );
                                          } else {
                                            remove('places', place);
                                          }
                                        },
                                        itemBuilder: (_) => const [
                                          PopupMenuItem(
                                            value: 'edit',
                                            child: AppText('Edit place'),
                                          ),
                                          PopupMenuItem(
                                            value: 'delete',
                                            child: AppText('Delete place'),
                                          ),
                                        ],
                                      ),
                                  ],
                                ),
                                Text(
                                  place['name'],
                                  maxLines: 1,
                                  overflow: TextOverflow.ellipsis,
                                  style: const TextStyle(
                                    fontSize: 20,
                                    fontWeight: FontWeight.w600,
                                  ),
                                ),
                                const Spacer(),
                                Text(
                                  '${place['tower_count'] ?? 0} towers',
                                  style: TextStyle(color: muted),
                                ),
                              ],
                            ),
                          ),
                        ),
                      ),
                    ),
                  )
                  .toList(),
            )
          else
            AppText(
              'Add a place to group your towers.',
              style: TextStyle(color: muted),
            ),
        ] else ...[
          Align(
            alignment: AlignmentDirectional.centerStart,
            child: TextButton.icon(
              onPressed: () => setState(() {
                placeFilter = null;
                search = '';
              }),
              icon: const Icon(Icons.arrow_back),
              label: const AppText('Back to places'),
            ),
          ),
          Text(
            placeFilter == ''
                ? 'Unassigned towers'
                : nameOf('places', placeFilter),
            style: const TextStyle(fontSize: 24, fontWeight: FontWeight.w600),
          ),
          const SizedBox(height: 16),
        ],
        if (placeFilter != null) ...[
          toolbar('towers'),
          Text(
            '${towers.length} ${towers.length == 1 ? 'tower' : 'towers'}',
            style: const TextStyle(fontSize: 22, fontWeight: FontWeight.w600),
          ),
          const SizedBox(height: 8),
          AppText(
            'Click a tower to view all its devices.',
            style: TextStyle(color: muted),
          ),
          const SizedBox(height: 20),
          if (towers.isEmpty)
            card(
              Text(
                search.isEmpty
                    ? 'No towers to display yet.'
                    : 'No towers match your search.',
                style: TextStyle(color: muted),
              ),
            )
          else
            LayoutBuilder(
              builder: (context, constraints) {
                final size = constraints.maxWidth.clamp(0.0, 240.0).toDouble();
                return Wrap(
                  spacing: 12,
                  runSpacing: 12,
                  children: towers.map((tower) {
                    final color = switch (tower['status']) {
                      'online' => green,
                      'offline' => red,
                      'warning' => orange,
                      _ => muted,
                    };
                    final count = deviceCounts[tower['id']] ?? 0;
                    final online = onlineCounts[tower['id']] ?? 0;
                    final offline = offlineCounts[tower['id']] ?? 0;
                    return SizedBox(
                      key: ValueKey('tower-card-${tower['id']}'),
                      width: size,
                      height: size,
                      child: Material(
                        color: panel,
                        shape: RoundedRectangleBorder(
                          borderRadius: BorderRadius.circular(16),
                          side: BorderSide(color: color.withValues(alpha: .35)),
                        ),
                        clipBehavior: Clip.antiAlias,
                        child: InkWell(
                          onTap: () => openTowerDevices(tower['id']),
                          child: Padding(
                            padding: const EdgeInsets.all(14),
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Row(
                                  children: [
                                    TowerMarker(statusColor: color),
                                    const Spacer(),
                                    badge(tower['status']),
                                    if (inventoryWriter || towerDeleter)
                                      SizedBox(
                                        width: 32,
                                        height: 36,
                                        child: PopupMenuButton<String>(
                                          tooltip: 'Tower actions',
                                          padding: EdgeInsets.zero,
                                          icon: Icon(
                                            Icons.more_vert,
                                            size: 20,
                                            color: muted,
                                          ),
                                          onSelected: (action) {
                                            if (action == 'discover_snmp') {
                                              discoverTower(
                                                Map<String, dynamic>.from(
                                                  tower,
                                                ),
                                                snmp: true,
                                              );
                                            } else if (action == 'discover') {
                                              discoverTower(
                                                Map<String, dynamic>.from(
                                                  tower,
                                                ),
                                              );
                                            } else if (action == 'edit') {
                                              edit(
                                                'towers',
                                                existing:
                                                    Map<String, dynamic>.from(
                                                      tower,
                                                    ),
                                              );
                                            } else if (action == 'delete') {
                                              remove('towers', tower);
                                            }
                                          },
                                          itemBuilder: (_) => [
                                            if (owner)
                                              const PopupMenuItem(
                                                value: 'discover_snmp',
                                                child: AppText(
                                                  'Discovery SNMP',
                                                ),
                                              ),
                                            if (inventoryWriter)
                                              const PopupMenuItem(
                                                value: 'discover',
                                                child: AppText(
                                                  'Discover devices',
                                                ),
                                              ),
                                            if (inventoryWriter)
                                              const PopupMenuItem(
                                                value: 'edit',
                                                child: AppText('Edit tower'),
                                              ),
                                            if (towerDeleter)
                                              const PopupMenuItem(
                                                value: 'delete',
                                                child: AppText('Delete tower'),
                                              ),
                                          ],
                                        ),
                                      ),
                                  ],
                                ),
                                const SizedBox(height: 8),
                                Tooltip(
                                  message: '${tower['name']}',
                                  child: Text(
                                    '${tower['name']}',
                                    maxLines: 1,
                                    overflow: TextOverflow.ellipsis,
                                    style: const TextStyle(
                                      fontSize: 20,
                                      fontWeight: FontWeight.w700,
                                    ),
                                  ),
                                ),
                                const SizedBox(height: 8),
                                Text(
                                  (tower['location']?.toString().isNotEmpty ??
                                          false)
                                      ? tower['location']
                                      : 'No location set',
                                  maxLines: 1,
                                  overflow: TextOverflow.ellipsis,
                                  style: TextStyle(color: muted),
                                ),
                                const SizedBox(height: 4),
                                Text(
                                  tower['management_ip']?.toString() ??
                                      'No management IP',
                                  maxLines: 1,
                                  overflow: TextOverflow.ellipsis,
                                  style: TextStyle(color: muted, fontSize: 12),
                                ),
                                const Spacer(),
                                Divider(
                                  color: themeColor(0xff20334e, 0xffd6dfeb),
                                ),
                                const SizedBox(height: 8),
                                Row(
                                  children: [
                                    for (final stat in [
                                      (
                                        count,
                                        'Devices',
                                        themeColor(0xffffffff, 0xff172b4d),
                                      ),
                                      (online, 'Online', green),
                                      (offline, 'Offline', red),
                                    ])
                                      Expanded(
                                        child: Column(
                                          crossAxisAlignment:
                                              CrossAxisAlignment.start,
                                          children: [
                                            Text(
                                              '${stat.$1}',
                                              style: TextStyle(
                                                color: stat.$3,
                                                fontSize: 20,
                                                fontWeight: FontWeight.w700,
                                              ),
                                            ),
                                            Text(
                                              stat.$2,
                                              style: TextStyle(
                                                color: muted,
                                                fontSize: 12,
                                              ),
                                            ),
                                          ],
                                        ),
                                      ),
                                  ],
                                ),
                              ],
                            ),
                          ),
                        ),
                      ),
                    );
                  }).toList(),
                );
              },
            ),
        ],
      ],
    );
  }

  Widget toolbar(String resource) => Padding(
    padding: const EdgeInsets.only(bottom: 20),
    child: Wrap(
      alignment: WrapAlignment.spaceBetween,
      spacing: 16,
      runSpacing: 16,
      children: [
        SizedBox(
          width: 300,
          child: TextField(
            key: ValueKey('$resource:$towerFilter:$placeFilter'),
            decoration: InputDecoration(
              prefixIcon: Icon(Icons.search),
              hintText: tr('Search inventory'),
            ),
            onChanged: (v) => setState(() => search = v),
          ),
        ),
        if ((resource == 'users' && owner) ||
            (resource == 'towers' &&
                owner &&
                placeFilter != null &&
                placeFilter != '') ||
            (['devices', 'sectors'].contains(resource) && inventoryWriter))
          FilledButton.icon(
            onPressed: () => edit(resource),
            icon: const Icon(Icons.add, size: 18),
            label: Text(
              'Add ${resource == 'users' ? 'account' : resource.substring(0, resource.length - 1)}',
            ),
          ),
      ],
    ),
  );
  Widget inventory(String resource) {
    final data = filtered(resource);
    if (resource == 'devices') {
      data.sort((a, b) => compareIpAddresses(a['ip_address'], b['ip_address']));
    }
    final columns = switch (resource) {
      'towers' => ['Name', 'Location', 'Management IP', 'Sectors', 'Status'],
      'sectors' => ['Name', 'Tower', 'SSID', 'Frequency', 'IP address'],
      'users' => ['Username', 'Role', 'Active', 'Created'],
      _ => [
        'Wireless SSID',
        'Registration clients',
        'ether1 speed',
        'Uptime',
        'Downtime',
        'IP address',
        'Status',
        'Vendor',
      ],
    };
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        if (resource == 'devices' && towerFilter != null) ...[
          Wrap(
            spacing: 16,
            runSpacing: 8,
            crossAxisAlignment: WrapCrossAlignment.center,
            children: [
              TextButton.icon(
                onPressed: () {
                  final place = placeFilter;
                  navigate(towerOrigin);
                  if (towerOrigin == pages.indexOf('Towers')) {
                    setState(() => placeFilter = place);
                  }
                },
                icon: const Icon(Icons.arrow_back),
                label: Text(
                  towerOrigin == pages.indexOf('NOC Screen')
                      ? 'Back to NOC Screen'
                      : towerOrigin == pages.indexOf('Network Map')
                      ? 'Back to Network Map'
                      : 'Back to Towers',
                ),
              ),
              Text(
                'Devices at ${nameOf('towers', towerFilter)}',
                style: const TextStyle(
                  fontSize: 22,
                  fontWeight: FontWeight.w600,
                ),
              ),
            ],
          ),
          const SizedBox(height: 20),
        ],
        toolbar(resource),
        if (resource == 'users' && owner)
          SnmpVisibilityControl(
            api: api,
            accounts: list('users'),
            onChanged: () => reload(quiet: true),
          ),
        section(
          '${data.length} ${resource == 'users' ? 'accounts' : resource}',
          data.isEmpty
              ? Padding(
                  padding: const EdgeInsets.all(24),
                  child: Text(
                    resource == 'devices' && towerFilter != null
                        ? (search.isEmpty
                              ? 'No devices are assigned to this tower yet.'
                              : 'No devices match this search in this tower.')
                        : 'No matching records. Add your inventory to begin monitoring.',
                    style: TextStyle(color: muted),
                  ),
                )
              : SingleChildScrollView(
                  scrollDirection: Axis.horizontal,
                  child: DataTable(
                    columns: [
                      ...columns.map((x) => DataColumn(label: Text(x))),
                      const DataColumn(label: AppText('Actions')),
                    ],
                    rows: data.map((row) {
                      List<dynamic> values = switch (resource) {
                        'towers' => [
                          row['name'],
                          row['location'],
                          row['management_ip'],
                          row['sector_count'],
                          badge(row['status']),
                        ],
                        'sectors' => [
                          row['name'],
                          nameOf('towers', row['tower_id']),
                          row['ssid'],
                          row['frequency_mhz'],
                          row['ip_address'],
                        ],
                        'users' => [
                          row['username'],
                          row['access_role_name'] ??
                              row['manager_role_name'] ??
                              row['role'],
                          row['active'],
                          row['created_at']?.toString().substring(0, 10),
                        ],
                        _ => [
                          deviceReading(row, 'wireless'),
                          wirelessClientCount(row),
                          deviceReading(row, 'ethernet_links'),
                          deviceReading(row, 'uptime_seconds'),
                          deviceDowntime(row),
                          row['ip_address'],
                          badge(row['status']),
                          row['vendor_label'] ?? row['vendor'],
                        ],
                      };
                      return DataRow(
                        cells: [
                          ...values.map(
                            (v) => DataCell(
                              v is Widget ? v : Text(v?.toString() ?? '—'),
                              onTap: resource == 'towers'
                                  ? () => openTowerDevices(row['id'])
                                  : null,
                            ),
                          ),
                          DataCell(
                            Row(
                              children: [
                                if (resource == 'towers')
                                  IconButton(
                                    tooltip: 'View tower devices',
                                    onPressed: () =>
                                        openTowerDevices(row['id']),
                                    icon: Icon(
                                      Icons.router_outlined,
                                      size: 19,
                                      color: blue,
                                    ),
                                  ),
                                if (resource == 'devices' &&
                                    row['vendor'] == 'mikrotik_switch')
                                  IconButton(
                                    key: ValueKey('manage-switch-${row['id']}'),
                                    tooltip: 'Manage switch',
                                    onPressed: () => showDialog<void>(
                                      context: context,
                                      builder: (_) => EthernetPortsDialog(
                                        api: api,
                                        device: Map<String, dynamic>.from(row),
                                      ),
                                    ),
                                    icon: const Icon(
                                      Icons.settings_ethernet,
                                      size: 19,
                                    ),
                                  ),
                                if (resource != 'users' && inventoryWriter)
                                  IconButton(
                                    tooltip: 'Edit',
                                    onPressed: () => edit(
                                      resource,
                                      existing: Map<String, dynamic>.from(row),
                                    ),
                                    icon: const Icon(
                                      Icons.edit_outlined,
                                      size: 19,
                                    ),
                                  ),
                                if (resource == 'users' &&
                                    owner &&
                                    row['role'] != 'owner') ...[
                                  if (row['role'] == 'manager' &&
                                      row['manager_role_id'] == null &&
                                      row['access_role_id'] == null &&
                                      row['access_policy_configured'] != true)
                                    TextButton.icon(
                                      label: const AppText('Section access'),
                                      icon: const Icon(
                                        Icons.admin_panel_settings_outlined,
                                        size: 19,
                                      ),
                                      onPressed: () async {
                                        final saved = await showDialog<bool>(
                                          context: context,
                                          barrierDismissible: false,
                                          builder: (_) => SectionAccessDialog(
                                            api: api,
                                            account: Map<String, dynamic>.from(
                                              row,
                                            ),
                                          ),
                                        );
                                        if (saved == true && mounted) {
                                          await reload();
                                          toast('Section access saved');
                                        }
                                      },
                                    ),
                                  IconButton(
                                    tooltip: 'Edit username, password or role',
                                    onPressed: () => editAccount(row),
                                    icon: const Icon(
                                      Icons.edit_outlined,
                                      size: 19,
                                    ),
                                  ),
                                  IconButton(
                                    tooltip: 'Delete account',
                                    onPressed: () => deleteAccount(row),
                                    icon: Icon(
                                      Icons.delete_outline,
                                      size: 19,
                                      color: red,
                                    ),
                                  ),
                                ],
                                if (resource == 'users' &&
                                    row['role'] == 'technician')
                                  IconButton(
                                    tooltip: 'Assign device',
                                    onPressed: () => assign(row['id']),
                                    icon: const Icon(Icons.link, size: 19),
                                  ),
                                if (resource == 'users' &&
                                    row['role'] != 'owner' &&
                                    row['active'] == true)
                                  IconButton(
                                    tooltip: 'Disable account',
                                    onPressed: () => remove(resource, row),
                                    icon: const Icon(
                                      Icons.person_off_outlined,
                                      size: 19,
                                    ),
                                  ),
                                if (resource != 'users' &&
                                    ((resource == 'towers' && towerDeleter) ||
                                        (resource != 'towers' &&
                                            inventoryDeleter)))
                                  IconButton(
                                    tooltip: 'Delete',
                                    onPressed: () => remove(resource, row),
                                    icon: Icon(
                                      Icons.delete_outline,
                                      size: 19,
                                      color: red,
                                    ),
                                  ),
                              ],
                            ),
                          ),
                        ],
                      );
                    }).toList(),
                  ),
                ),
        ),
      ],
    );
  }

  Future<void> editAccount(Map row) async {
    if (!await refreshAccountRoles()) return;
    if (!mounted) return;
    final result = await showDialog<Map<String, dynamic>>(
      context: context,
      builder: (_) => ResourceDialog(
        title: 'Edit account',
        fields: [
          FieldSpec('username', 'Username', required: true),
          accountTypeField(),
          FieldSpec(
            'password',
            'New password (leave blank to keep current)',
            kind: 'password',
          ),
          FieldSpec(
            'confirm_password',
            'Confirm new password',
            kind: 'password',
          ),
          managerParentField(account: row),
          managerPlacesField(),
          FieldSpec(
            'show_snmp_profiles',
            'Show SNMP profiles',
            kind: 'bool',
            initial: false,
          ),
        ],
        initial: {
          'username': row['username'],
          'role': row['access_role_id'] != null
              ? 'custom:${row['access_role_id']}'
              : row['role'],
          'parent_id': row['parent_id'] ?? '',
          'place_ids': row['place_ids'] ?? [],
          'show_snmp_profiles': row['show_snmp_profiles'] == true,
        },
        save: (data) async {
          if (data['password'] != data['confirm_password']) {
            throw const FormatException('New passwords do not match.');
          }
          await api.request(
            '/users/${row['id']}',
            method: 'PUT',
            body: {
              'username': data['username'],
              'password': data['password'],
              'role': data['role'],
              if (data.containsKey('show_snmp_profiles'))
                'show_snmp_profiles': data['show_snmp_profiles'],
              if (data.containsKey('parent_id')) 'parent_id': data['parent_id'],
              if (data.containsKey('place_ids')) 'place_ids': data['place_ids'],
              if (data.containsKey('access_role_id'))
                'access_role_id': data['access_role_id'],
            },
          );
        },
      ),
    );
    if (result != null) {
      await reload();
      toast('Account updated. Use the updated credentials to sign in.');
    }
  }

  Future<void> deleteAccount(Map row) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text('Delete account ${row['username']}?'),
        content: const AppText(
          'This permanently deletes the account and ends its sessions. Assigned towers become unassigned; towers and devices are kept.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const AppText('Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: const AppText('Delete account'),
          ),
        ],
      ),
    );
    if (confirmed != true) return;
    try {
      await api.request('/users/${row['id']}', method: 'DELETE');
      await reload();
      toast('Account deleted');
    } catch (e) {
      toast(e.toString());
    }
  }

  Future<void> remove(String resource, Map row) async {
    final ok = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text(
          resource == 'users' ? 'Disable account?' : 'Delete ${row['name']}?',
        ),
        content: const AppText(
          'This changes the saved inventory. Resources with dependents must be emptied first.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const AppText('Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: const AppText('Confirm'),
          ),
        ],
      ),
    );
    if (ok != true) return;
    try {
      await api.request(
        '/$resource/${row['id']}${resource == 'users' ? '/disable' : ''}',
        method: resource == 'users' ? 'POST' : 'DELETE',
      );
      await reload();
    } catch (e) {
      toast(e.toString());
    }
  }

  Future<void> assign(String userId) async {
    String? id;
    final ok = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const AppText('Assign a device'),
        content: DropdownButtonFormField<String>(
          items: list('devices')
              .map(
                (d) => DropdownMenuItem<String>(
                  value: d['id'],
                  child: Text(d['name']),
                ),
              )
              .toList(),
          onChanged: (v) => id = v,
        ),
        actions: [
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: const AppText('Assign'),
          ),
        ],
      ),
    );
    if (ok == true && id != null) {
      try {
        await api.request('/users/$userId/devices/$id', method: 'PUT');
        toast('Device assigned');
      } catch (e) {
        toast(e.toString());
      }
    }
  }

  Future<void> manageDevice(Map<String, dynamic> device) async {
    await showDialog<void>(
      context: context,
      barrierDismissible: false,
      builder: (_) => DeviceManagementDialog(
        api: api,
        device: device,
        canEdit: inventoryWriter,
      ),
    );
  }

  Future<void> discoverTower(
    Map<String, dynamic> tower, {
    bool snmp = false,
  }) async {
    await showDialog<void>(
      context: context,
      barrierDismissible: false,
      builder: (_) => TowerDiscoveryDialog(
        api: api,
        tower: tower,
        snmp: snmp,
        onManageDevice: manageDevice,
      ),
    );
    if (mounted) await reload();
  }

  Future<void> edit(String resource, {Map<String, dynamic>? existing}) async {
    if (resource == 'users' && !await refreshAccountRoles()) return;
    if (resource == 'devices' && owner) {
      try {
        final profiles = await api.request('/snmp-profiles');
        if (!mounted) return;
        setState(() => rows['snmp-profiles'] = profiles as List);
      } catch (e) {
        if (mounted) toast(e.toString());
        return;
      }
    }
    if (!mounted) return;
    if (resource == 'snmp-profiles') {
      final saved = await showDialog<bool>(
        context: context,
        barrierDismissible: false,
        builder: (_) => SnmpProfileDialog(api: api),
      );
      if (saved == true && mounted) await reload();
      return;
    }
    final specs = [
      ...fields(resource),
      if (resource == 'towers' && existing == null)
        FieldSpec(
          'discover_after_save',
          'Discover devices after saving',
          kind: 'bool',
          initial: false,
        ),
    ];
    Map<String, dynamic>? savedTower;
    String? savedPlace;
    bool discover = false;
    final initial = <String, dynamic>{
      for (final f in specs) f.key: existing?[f.key] ?? f.initial,
    };
    if (resource == 'towers' && existing == null) {
      initial['place_id'] = placeFilter;
    }
    if (resource == 'towers' &&
        existing?['latitude'] != null &&
        existing?['longitude'] != null) {
      initial['gps'] = '${existing!['latitude']}, ${existing['longitude']}';
    }
    final result = await showDialog<Map<String, dynamic>>(
      context: context,
      builder: (context) => ResourceDialog(
        title:
            '${existing == null ? 'Add' : 'Edit'} ${resource == 'users'
                ? 'account'
                : resource == 'places'
                ? 'place'
                : resource}',
        fields: specs,
        initial: initial,
        save: (data) async {
          final payload = Map<String, dynamic>.from(data);
          discover = payload.remove('discover_after_save') == true;
          if (resource == 'devices') {
            final profile = payload['snmp_profile_id'];
            if (profile is String && profile.startsWith('preset:')) {
              final savedProfile = await api.request(
                '/snmp-profiles/discovery-public',
                method: 'POST',
                body: {'version': profile.split(':').last},
              );
              payload['snmp_profile_id'] = savedProfile['id'];
            }
          }
          if (resource == 'towers') {
            final gps = (payload.remove('gps') as String? ?? '').trim();
            double? latitude;
            double? longitude;
            if (gps.isNotEmpty) {
              final parts = gps.split(',');
              if (parts.length == 2) {
                latitude = double.tryParse(parts[0].trim());
                longitude = double.tryParse(parts[1].trim());
              }
              if (latitude == null ||
                  longitude == null ||
                  !latitude.isFinite ||
                  !longitude.isFinite ||
                  latitude < -90 ||
                  latitude > 90 ||
                  longitude < -180 ||
                  longitude > 180) {
                throw const FormatException(
                  'Enter GPS as latitude, longitude (for example: 37.1445, 42.6872).',
                );
              }
            }
            payload['latitude'] = latitude;
            payload['longitude'] = longitude;
          }
          final saved = await api.request(
            '/$resource${existing == null ? '' : '/${existing['id']}'}',
            method: existing == null ? 'POST' : 'PUT',
            body: payload,
          );
          if (resource == 'places') savedPlace = saved['id'];
          if (resource == 'towers') {
            savedTower = Map<String, dynamic>.from(saved);
          }
        },
      ),
    );
    if (result != null) {
      await reload();
      if (mounted &&
          resource == 'places' &&
          existing == null &&
          savedPlace != null) {
        setState(() {
          placeFilter = savedPlace;
          search = '';
        });
      }
      if (mounted && discover && savedTower != null) {
        await discoverTower(savedTower!);
      }
    }
  }

  FieldSpec accountTypeField({bool allowOwner = false}) => FieldSpec(
    'role',
    'Account type',
    kind: 'account_type',
    required: true,
    initial: list('access-roles').any((r) => r['account_type'] == 'manager')
        ? 'manager'
        : null,
    options: [
      ...list('access-roles')
          .where((r) => allowOwner || r['account_type'] != 'owner')
          .map(
            (r) => Option(
              r['built_in'] == true ? r['account_type'] : 'custom:${r['id']}',
              r['name'],
            ),
          ),
    ],
  );

  Future<bool> refreshAccountRoles() async {
    try {
      final data = await Future.wait([
        api.request('/access-roles'),
        api.request('/users'),
      ]);
      if (!mounted) return false;
      setState(() {
        rows['access-roles'] = data[0] as List;
        rows['users'] = data[1] as List;
      });
      return true;
    } catch (e) {
      if (mounted) toast(e.toString());
      return false;
    }
  }

  FieldSpec managerParentField({Map? account}) {
    final excluded = <String>{if (account != null) account['id'] as String};
    final accounts = list('users');
    var added = true;
    while (added) {
      added = false;
      for (final manager in accounts) {
        if (excluded.contains(manager['parent_id']) &&
            excluded.add(manager['id'] as String)) {
          added = true;
        }
      }
    }
    return FieldSpec(
      'parent_id',
      'Parent manager',
      kind: 'manager_parent',
      initial: '',
      options: [
        const Option('', 'None'),
        ...accounts
            .where(
              (manager) =>
                  manager['role'] == 'manager' &&
                  (manager['active'] == true ||
                      manager['id'] == account?['parent_id']) &&
                  !excluded.contains(manager['id']),
            )
            .map(
              (manager) => Option(
                manager['id'],
                '${manager['username']}${manager['active'] == true ? '' : ' (inactive)'}',
              ),
            ),
      ],
    );
  }

  FieldSpec managerPlacesField() => FieldSpec(
    'place_ids',
    'Assigned places',
    kind: 'multiselect',
    initial: const <String>[],
    options: list(
      'places',
    ).map((place) => Option(place['id'], place['name'])).toList(),
  );

  List<FieldSpec> fields(String resource) {
    List<Option> options(String kind, {bool nullable = false}) => [
      if (nullable) const Option('', 'None'),
      ...list(kind).map((x) => Option(x['id'], x['name'] ?? x['username'])),
    ];
    final towers = options('towers');
    switch (resource) {
      case 'places':
        return [FieldSpec('name', 'Place name', required: true)];
      case 'towers':
        return [
          FieldSpec('name', 'Tower name', required: true),
          if (owner)
            FieldSpec(
              'place_id',
              'Place',
              options: options('places', nullable: true),
            ),
          FieldSpec('location', 'Location', initial: ''),
          FieldSpec('gps', 'GPS (latitude, longitude)'),
          FieldSpec('management_ip', 'Management IP'),
          if (owner) ...[
            FieldSpec(
              'api_enabled',
              'Monitor tower devices using API (RouterOS REST / airOS)',
              kind: 'bool',
              initial: false,
            ),
            FieldSpec(
              'api_username',
              'Device API username (all devices in this tower)',
              initial: '',
            ),
            FieldSpec(
              'api_password',
              'Device API password (blank keeps saved password)',
              kind: 'password',
            ),
            FieldSpec(
              'api_protocol',
              'Device API connection',
              initial: 'https',
              options: [
                const Option('https', 'HTTPS'),
                const Option('http', 'HTTP (unencrypted)'),
                const Option('both', 'HTTPS + HTTP (auto)'),
              ],
            ),
            FieldSpec(
              'api_port',
              'Device API port (blank uses 443 / 80)',
              kind: 'int',
            ),
            FieldSpec(
              'api_verify_tls',
              'Verify device HTTPS certificate',
              kind: 'bool',
              initial: true,
            ),
          ],
        ];
      case 'sectors':
        return [
          FieldSpec('name', 'Sector name', required: true),
          FieldSpec(
            'tower_id',
            'Parent tower',
            required: true,
            options: towers,
          ),
          FieldSpec('ssid', 'SSID', initial: ''),
          FieldSpec('frequency_mhz', 'Frequency (MHz)', kind: 'int'),
          FieldSpec('channel_width_mhz', 'Channel width (MHz)', kind: 'int'),
          FieldSpec('model', 'Device model', initial: ''),
          FieldSpec('ip_address', 'IP address'),
        ];
      case 'users':
        return [
          FieldSpec('username', 'Username', required: true),
          FieldSpec(
            'password',
            'Password (at least 14 characters)',
            required: true,
            kind: 'password',
          ),
          accountTypeField(allowOwner: true),
          managerParentField(),
          managerPlacesField(),
          FieldSpec(
            'show_snmp_profiles',
            'Show SNMP profiles',
            kind: 'bool',
            initial: api.user?['default_snmp_profile_visibility'] == true,
          ),
        ];
      default:
        return [
          FieldSpec('name', 'Device name', required: true),
          FieldSpec('ip_address', 'Management IP', required: true),
          FieldSpec('tower_id', 'Tower', required: true, options: towers),
          FieldSpec(
            'sector_id',
            'Sector',
            options: options('sectors', nullable: true),
          ),
          FieldSpec(
            'vendor',
            'Vendor',
            initial: 'generic',
            options: const [
              Option('generic', 'Auto detect (SNMP / API)'),
              Option('mikrotik', 'MikroTik'),
              Option('mikrotik_switch', 'MikroTik switch'),
              Option('ubiquiti', 'Ubiquiti (other airMAX)'),
              Option('ubiquiti_m5', 'Ubiquiti airMAX M5'),
              Option('ubiquiti_ac', 'Ubiquiti airMAX AC'),
              Option('mimosa', 'Mimosa'),
            ],
          ),
          FieldSpec('model', 'Model', initial: ''),
          FieldSpec(
            'snmp_profile_id',
            'SNMP profile',
            kind: owner ? 'snmp_profile' : 'text',
            helperText: owner
                ? 'Presets use community public. For another community or SNMP v3, choose a saved profile from Settings. Works with SNMP-enabled models; the device credentials must match.'
                : null,
            options: owner
                ? [
                    const Option('', 'None'),
                    const Option(
                      'preset:mikrotik_switch:2c',
                      'MikroTik switch — SNMP v2c / public',
                    ),
                    for (final vendor in const [
                      (
                        key: 'mikrotik',
                        label: 'MikroTik (all models)',
                        versions: ['2c', '1'],
                      ),
                      (
                        key: 'ubiquiti',
                        label: 'UBNT (M5 / AC / other models)',
                        versions: ['2c', '1'],
                      ),
                      (
                        key: 'mimosa',
                        label: 'Mimosa (all models)',
                        versions: ['2c'],
                      ),
                    ])
                      for (final version in vendor.versions)
                        Option(
                          'preset:${vendor.key}:$version',
                          '${vendor.label} — SNMP v${version == '2c' ? '2c' : version} / public',
                        ),
                    ...list('snmp-profiles').map(
                      (profile) => Option(
                        profile['id'],
                        '${profile['name']} — SNMP v${profile['version'] == '2' ? '2c' : profile['version'] ?? '?'}',
                      ),
                    ),
                  ]
                : null,
          ),
          FieldSpec(
            'connection_timeout',
            'Connection timeout (seconds)',
            kind: 'int',
            required: true,
            initial: 2,
            min: 1,
            max: 30,
            helperText: 'Wait per monitoring connection attempt: 1–30 seconds.',
          ),
          FieldSpec(
            'poll_interval',
            'Update interval (seconds)',
            kind: 'int',
            required: true,
            initial: 60,
            min: 15,
            max: 86400,
            helperText: 'Time between monitoring checks: 15–86400 seconds.',
          ),
          FieldSpec('retries', 'Retry limit', kind: 'int', initial: 2),
          FieldSpec(
            'failure_threshold',
            'Failure threshold',
            kind: 'int',
            initial: 3,
          ),
          FieldSpec(
            'cpu_threshold',
            'CPU warning (%)',
            kind: 'number',
            initial: 90,
          ),
          FieldSpec(
            'enabled',
            'Monitoring enabled',
            kind: 'bool',
            initial: true,
          ),
        ];
    }
  }

  Widget monitoring() {
    final points = samples.map((m) {
      final interfaces = (m['values']['interfaces'] as Map?) ?? {};
      final rates = interfaces.values
          .where((v) => v['rx_bps'] != null)
          .map((v) => (v['rx_bps'] as num).toDouble() / 1000000)
          .toList();
      return rates.isEmpty ? null : rates.reduce((a, b) => a + b);
    }).toList();
    return section(
      'Bandwidth & monitoring history',
      Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 420,
            child: DropdownButtonFormField<String>(
              initialValue: list('devices').any((d) => d['id'] == deviceId)
                  ? deviceId
                  : null,
              isExpanded: true,
              decoration: InputDecoration(
                labelText: tr('Select monitored device'),
              ),
              items: list('devices')
                  .map(
                    (d) => DropdownMenuItem<String>(
                      value: d['id'],
                      child: Text('${d['name']} · ${d['ip_address']}'),
                    ),
                  )
                  .toList(),
              onChanged: (v) {
                if (v != null) loadMetrics(v);
              },
            ),
          ),
          const SizedBox(height: 24),
          if (deviceId != null) ...[
            DeviceDowntimeHistory(api: api, deviceId: deviceId!),
            const SizedBox(height: 24),
          ],
          if (samples.isEmpty)
            SizedBox(
              height: 160,
              child: Center(
                child: AppText(
                  'Select a device with collected samples to view real telemetry.',
                  style: TextStyle(color: muted),
                ),
              ),
            )
          else ...[
            SizedBox(
              height: 190,
              width: double.infinity,
              child: CustomPaint(painter: HistoryChart(points)),
            ),
            const SizedBox(height: 12),
            AppText(
              'RX Mbit/s · sum of device interfaces · missing samples shown as gaps',
              style: TextStyle(color: muted, fontSize: 12),
            ),
            const SizedBox(height: 20),
            Wrap(
              spacing: 28,
              runSpacing: 16,
              children: [
                for (final field in [
                  'cpu_percent',
                  'memory_percent',
                  'uptime_seconds',
                  'icmp_up',
                  'snmp_up',
                  'wireless_clients',
                  'weakest_signal_dbm',
                  'radio_frequencies_mhz',
                ])
                  Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        field.replaceAll('_', ' '),
                        style: TextStyle(color: muted, fontSize: 12),
                      ),
                      Text(
                        samples.last['values'][field] is List
                            ? (samples.last['values'][field] as List).join(', ')
                            : value(samples.last['values'][field]),
                        style: const TextStyle(fontSize: 20),
                      ),
                    ],
                  ),
              ],
            ),
          ],
        ],
      ),
    );
  }

  Widget clients() => ispReports
      ? Sas4Reports(key: ValueKey('reports-$accountRevision'), api: api)
      : Sas4Clients(
          key: ValueKey('$accountRevision-$ispDashboard-$ispOnline'),
          api: api,
          showDashboard: ispDashboard,
          showOnline: ispOnline,
        );

  Widget alertsView({bool recent = false}) {
    final data = (recent ? list('alerts').take(5) : list('alerts')).toList();
    return section(
      recent ? 'Recent alerts' : 'Alerts',
      data.isEmpty
          ? AppText('No alerts recorded.', style: TextStyle(color: muted))
          : Column(
              children: data
                  .map(
                    (a) => ListTile(
                      contentPadding: EdgeInsets.zero,
                      leading: Icon(
                        a['severity'] == 'critical'
                            ? Icons.error_outline
                            : Icons.warning_amber,
                        color: a['resolved_at'] != null
                            ? muted
                            : a['severity'] == 'critical'
                            ? red
                            : orange,
                      ),
                      title: Text(a['message']),
                      subtitle: Text(
                        '${nameOf('devices', a['device_id'])} · ${a['opened_at']}\n${a['resolved_at'] != null
                            ? 'Resolved'
                            : a['acknowledged_by'] != null
                            ? 'Acknowledged'
                            : 'Open'}',
                        style: TextStyle(color: muted, fontSize: 12),
                      ),
                      trailing:
                          ((role == 'technician' &&
                                      !usesSectionPermissions(api.user!)) ||
                                  canEditSection(api.user!, 'alerts')) &&
                              a['acknowledged_by'] == null
                          ? TextButton(
                              onPressed: () async {
                                try {
                                  await api.request(
                                    '/alerts/${a['id']}/acknowledge',
                                    method: 'POST',
                                  );
                                  await reload();
                                } catch (e) {
                                  toast(e.toString());
                                }
                              },
                              child: const AppText('Acknowledge'),
                            )
                          : null,
                    ),
                  )
                  .toList(),
            ),
    );
  }

  Widget networkMap() => NetworkMap(
    towers: list('towers'),
    expanded: mapExpanded,
    toggleExpanded: () => setState(() => mapExpanded = !mapExpanded),
    openDevices: openTowerDevices,
  );

  Widget networkTopology() {
    final towers = filtered(
      'towers',
    ).where((t) => t['latitude'] != null && t['longitude'] != null).toList();
    LatLng point(dynamic t) => LatLng(
      (t['latitude'] as num).toDouble(),
      (t['longitude'] as num).toDouble(),
    );
    return Column(
      children: [
        toolbar('map'),
        section(
          'Geographic network map',
          Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              AppText(
                'Only towers with saved coordinates are shown. Links require owner-entered verification evidence.',
                style: TextStyle(color: muted),
              ),
              const SizedBox(height: 16),
              if (towers.isEmpty)
                const SizedBox(
                  height: 320,
                  child: Center(
                    child: AppText(
                      'Add GPS coordinates to a tower to place it on the map.',
                    ),
                  ),
                )
              else
                SizedBox(
                  height: 520,
                  child: ClipRRect(
                    borderRadius: BorderRadius.circular(12),
                    child: FlutterMap(
                      options: MapOptions(
                        initialCenter: point(towers.first),
                        initialZoom: 10,
                      ),
                      children: [
                        TileLayer(
                          urlTemplate:
                              'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
                          userAgentPackageName: 'com.airlink.isp_os',
                        ),
                        PolylineLayer(
                          polylines: list('links')
                              .where(
                                (l) =>
                                    towers.any(
                                      (t) => t['id'] == l['source_id'],
                                    ) &&
                                    towers.any(
                                      (t) => t['id'] == l['target_id'],
                                    ),
                              )
                              .map(
                                (l) => Polyline(
                                  points: [
                                    point(
                                      towers.firstWhere(
                                        (t) => t['id'] == l['source_id'],
                                      ),
                                    ),
                                    point(
                                      towers.firstWhere(
                                        (t) => t['id'] == l['target_id'],
                                      ),
                                    ),
                                  ],
                                  color: blue,
                                  strokeWidth: 3,
                                ),
                              )
                              .toList(),
                        ),
                        MarkerLayer(
                          markers: towers
                              .map(
                                (t) => Marker(
                                  point: point(t),
                                  width: 64,
                                  height: 72,
                                  alignment: Alignment.topCenter,
                                  child: IconButton(
                                    tooltip: t['name'],
                                    padding: EdgeInsets.zero,
                                    iconSize: 58,
                                    icon: TowerMarker(
                                      mapPin: true,
                                      statusColor: t['status'] == 'online'
                                          ? green
                                          : t['status'] == 'offline'
                                          ? red
                                          : t['status'] == 'warning'
                                          ? orange
                                          : muted,
                                      size: 48,
                                    ),
                                    onPressed: () => showDialog(
                                      context: context,
                                      builder: (context) => AlertDialog(
                                        title: Text(t['name']),
                                        content: SizedBox(
                                          width: 380,
                                          child: SingleChildScrollView(
                                            child: Column(
                                              crossAxisAlignment:
                                                  CrossAxisAlignment.start,
                                              children: [
                                                badge(t['status']),
                                                Text(
                                                  '${t['location']}\n${t['management_ip'] ?? 'No management IP'}',
                                                ),
                                                const Divider(),
                                                ...list('sectors')
                                                    .where(
                                                      (s) =>
                                                          s['tower_id'] ==
                                                          t['id'],
                                                    )
                                                    .map(
                                                      (s) => Text(
                                                        'Sector: ${s['name']} · ${s['ssid']}',
                                                      ),
                                                    ),
                                                ...list('devices')
                                                    .where(
                                                      (d) =>
                                                          d['tower_id'] ==
                                                          t['id'],
                                                    )
                                                    .map(
                                                      (d) => Text(
                                                        '${d['name']} · ${d['ip_address']} · ${d['status']}',
                                                      ),
                                                    ),
                                              ],
                                            ),
                                          ),
                                        ),
                                        actions: [
                                          TextButton(
                                            onPressed: () =>
                                                Navigator.pop(context),
                                            child: const AppText('Close'),
                                          ),
                                        ],
                                      ),
                                    ),
                                  ),
                                ),
                              )
                              .toList(),
                        ),
                        const RichAttributionWidget(
                          attributions: [
                            TextSourceAttribution(
                              '© OpenStreetMap contributors',
                            ),
                          ],
                        ),
                      ],
                    ),
                  ),
                ),
              const SizedBox(height: 12),
              AppText(
                'Map tiles require internet access. Inventory and monitoring remain local.',
                style: TextStyle(color: muted, fontSize: 12),
              ),
              if (owner)
                TextButton.icon(
                  onPressed: () => showDialog(
                    context: context,
                    builder: (context) => ResourceDialog(
                      title: 'Verify network link',
                      fields: [
                        FieldSpec(
                          'source_id',
                          'Source tower',
                          required: true,
                          options: list(
                            'towers',
                          ).map((t) => Option(t['id'], t['name'])).toList(),
                        ),
                        FieldSpec(
                          'target_id',
                          'Target tower',
                          required: true,
                          options: list(
                            'towers',
                          ).map((t) => Option(t['id'], t['name'])).toList(),
                        ),
                        FieldSpec(
                          'evidence',
                          'Verification evidence (10+ characters)',
                          required: true,
                        ),
                      ],
                      initial: const {},
                      save: (data) async {
                        await api.request('/links', method: 'POST', body: data);
                        await reload();
                      },
                    ),
                  ),
                  icon: const Icon(Icons.add_link),
                  label: const AppText('Add verified link'),
                ),
            ],
          ),
        ),
      ],
    );
  }

  Widget reports() => section(
    'Availability reports',
    Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        AppText(
          'The report uses observed ICMP samples from the last 24 hours. Unsampled time is not counted as uptime.',
          style: TextStyle(color: muted),
        ),
        const SizedBox(height: 20),
        FilledButton.icon(
          onPressed: () async {
            try {
              final csv = await api.request('/reports/availability.csv');
              if (!mounted) return;
              showDialog(
                context: context,
                builder: (context) => AlertDialog(
                  title: const AppText('Availability CSV'),
                  content: SizedBox(
                    width: 700,
                    child: SingleChildScrollView(child: SelectableText(csv)),
                  ),
                  actions: [
                    TextButton(
                      onPressed: () => Navigator.pop(context),
                      child: const AppText('Close'),
                    ),
                  ],
                ),
              );
            } catch (e) {
              toast(e.toString());
            }
          },
          icon: const Icon(Icons.table_view_outlined),
          label: const AppText('Generate report'),
        ),
      ],
    ),
  );
  Widget updates() => section('Software Update Center', UpdateCenter(api: api));

  Map<String, IconData> get settingsPages => {
    if (canViewSnmpProfiles(api.user!)) 'SNMP profiles': Icons.key_outlined,
    if (canManageSettings) ...{
      'Payment gateways': Icons.payments_outlined,
      if (owner) 'Device API logins': Icons.router_outlined,
      'Network': Icons.settings_ethernet,
      'Audit log': Icons.history,
    },
    'Session & permissions': Icons.security_outlined,
  };

  Widget settings() {
    final selected = settingsPages.containsKey(settingsPage)
        ? settingsPage
        : null;
    if (selected == null) {
      return Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const AppText('Choose a settings page'),
          const SizedBox(height: 20),
          Wrap(
            spacing: 16,
            runSpacing: 16,
            children: [
              for (final entry in settingsPages.entries)
                SizedBox(
                  width: 252,
                  child: Card(
                    margin: EdgeInsets.zero,
                    child: ListTile(
                      contentPadding: const EdgeInsets.symmetric(
                        horizontal: 20,
                        vertical: 16,
                      ),
                      leading: Icon(entry.value, color: blue),
                      title: AppText(entry.key),
                      trailing: const Icon(Icons.chevron_right),
                      onTap: () => setState(() => settingsPage = entry.key),
                    ),
                  ),
                ),
            ],
          ),
        ],
      );
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        TextButton.icon(
          onPressed: () => setState(() => settingsPage = null),
          icon: const Icon(Icons.arrow_back),
          label: const AppText('Back to Settings'),
        ),
        const SizedBox(height: 12),
        AppText(
          selected,
          style: const TextStyle(fontSize: 22, fontWeight: FontWeight.w600),
        ),
        const SizedBox(height: 20),
        KeyedSubtree(
          key: ValueKey('settings-$selected'),
          child: settingsContent(selected),
        ),
      ],
    );
  }

  Widget settingsContent(String selected) {
    switch (selected) {
      case 'Payment gateways':
        return card(PaymentSettings(api: api, initiallyExpanded: true));
      case 'Device API logins':
        return card(DeviceApiAccessPanel(api: api, initiallyExpanded: true));
      case 'SNMP profiles':
        return section(
          'SNMP credential profiles',
          Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              AppText(
                'SNMP v1 / v2 communities and SNMP v3 credentials are encrypted on the server and cannot be read back.',
                style: TextStyle(color: muted),
              ),
              const SizedBox(height: 16),
              for (final p in list('snmp-profiles'))
                ListTile(
                  leading: const Icon(Icons.key),
                  title: Text(p['name']),
                  subtitle: Text(
                    'SNMP v${p['version'] == '2c' ? '2' : p['version'] ?? '3'}',
                  ),
                ),
              if (canManageSettings)
                FilledButton.icon(
                  onPressed: canEditSection(api.user!, 'settings')
                      ? () => edit('snmp-profiles')
                      : null,
                  icon: const Icon(Icons.add),
                  label: const AppText('Add SNMP profile'),
                ),
            ],
          ),
        );
      case 'Network':
        return NetworkSettings(api: api);
      case 'Audit log':
        return section(
          'Audit trail',
          FilledButton(
            onPressed: () async {
              try {
                final data = await api.request('/audit');
                if (!mounted) return;
                showDialog(
                  context: context,
                  builder: (context) => AlertDialog(
                    title: const AppText('Recent administrative events'),
                    content: SizedBox(
                      width: 600,
                      height: 400,
                      child: ListView(
                        children: (data as List)
                            .map(
                              (e) => ListTile(
                                title: Text(e['action']),
                                subtitle: Text(
                                  '${e['created_at']} · ${e['target'] ?? ''}',
                                ),
                              ),
                            )
                            .toList(),
                      ),
                    ),
                    actions: [
                      TextButton(
                        onPressed: () => Navigator.pop(context),
                        child: const AppText('Close'),
                      ),
                    ],
                  ),
                );
              } catch (e) {
                toast(e.toString());
              }
            },
            child: const AppText('View audit log'),
          ),
        );
      default:
        return notice(
          'Session & permissions',
          'Signed in as ${api.user!['username']} ($role). Access is enforced by the server on every request.',
        );
    }
  }
}

class Option {
  final String value, label;
  const Option(this.value, this.label);
}

class FieldSpec {
  final String key, label, kind;
  final bool required;
  final dynamic initial;
  final List<Option>? options;
  final String? helperText;
  final num? min, max;
  FieldSpec(
    this.key,
    this.label, {
    this.kind = 'text',
    this.required = false,
    this.initial,
    this.options,
    this.helperText,
    this.min,
    this.max,
  });
}

class ResourceDialog extends StatefulWidget {
  final String title;
  final List<FieldSpec> fields;
  final Map<String, dynamic> initial;
  final Future<void> Function(Map<String, dynamic>) save;
  const ResourceDialog({
    super.key,
    required this.title,
    required this.fields,
    required this.initial,
    required this.save,
  });
  @override
  State<ResourceDialog> createState() => _ResourceDialogState();
}

class _ResourceDialogState extends State<ResourceDialog> with LanguageRebuild {
  final form = GlobalKey<FormState>();
  final controls = <String, TextEditingController>{};
  final values = <String, dynamic>{};
  final changedSelections = <String>{};
  bool get managerSelected =>
      values['role'] == 'manager' ||
      (values['role'] is String &&
          (values['role'] as String).startsWith('custom:'));
  bool busy = false;
  String? error;
  @override
  void initState() {
    super.initState();
    for (final f in widget.fields) {
      final v = widget.initial[f.key] ?? f.initial;
      values[f.key] = v;
      controls[f.key] = TextEditingController(text: v?.toString() ?? '');
    }
    defaultVendorProfile();
  }

  static const mimosaPublicProfile = 'preset:mimosa:2c';

  void defaultVendorProfile() {
    final preset = switch (values['vendor']) {
      'mimosa' => mimosaPublicProfile,
      'mikrotik_switch' => 'preset:mikrotik_switch:2c',
      _ => null,
    };
    if (preset != null &&
        (values['snmp_profile_id'] == null ||
            values['snmp_profile_id'] == '') &&
        !changedSelections.contains('snmp_profile_id') &&
        widget.fields.any(
          (f) =>
              f.kind == 'snmp_profile' &&
              (f.options?.any((o) => o.value == preset) ?? false),
        )) {
      values['snmp_profile_id'] = preset;
    }
  }

  Widget snmpProfileField(FieldSpec field) {
    final selected = values[field.key] as String?;
    final preset = selected?.startsWith('preset:') == true;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        DropdownButtonFormField<String>(
          key: ValueKey('snmp-profile:$selected'),
          initialValue: field.options!.any((o) => o.value == selected)
              ? selected
              : null,
          isExpanded: true,
          decoration: InputDecoration(
            labelText: tr(field.label),
            helperText: field.helperText,
            helperMaxLines: 4,
          ),
          items: field.options!
              .map(
                (o) => DropdownMenuItem(value: o.value, child: Text(o.label)),
              )
              .toList(),
          onChanged: busy
              ? null
              : (value) => setState(() {
                  values[field.key] = value;
                  changedSelections.add(field.key);
                }),
        ),
        if (preset) ...[
          const SizedBox(height: 12),
          TextFormField(
            key: ValueKey('snmp-version:$selected'),
            initialValue: 'SNMPv${selected!.split(':').last}',
            readOnly: true,
            decoration: const InputDecoration(labelText: 'SNMP version'),
          ),
          const SizedBox(height: 12),
          TextFormField(
            initialValue: 'public',
            readOnly: true,
            decoration: const InputDecoration(
              labelText: 'SNMP Community String',
              helperText:
                  'Choose a saved profile to use a different community.',
              helperMaxLines: 2,
            ),
          ),
        ],
        if (values['vendor'] == 'mimosa' && selected != mimosaPublicProfile)
          Padding(
            padding: const EdgeInsets.only(top: 12),
            child: OutlinedButton(
              onPressed: busy
                  ? null
                  : () => setState(() {
                      values[field.key] = mimosaPublicProfile;
                      changedSelections.add(field.key);
                    }),
              child: const Text('Use Mimosa SNMPv2c / public'),
            ),
          ),
      ],
    );
  }

  @override
  void dispose() {
    for (final c in controls.values) {
      c.dispose();
    }
    super.dispose();
  }

  Future<void> submit() async {
    if (!form.currentState!.validate()) return;
    setState(() {
      busy = true;
      error = null;
    });
    try {
      final data = <String, dynamic>{};
      for (final f in widget.fields) {
        if (f.kind == 'account_type') {
          final selected = values[f.key] as String;
          if (selected.startsWith('custom:')) {
            data['role'] = 'manager';
            data['access_role_id'] = selected.substring('custom:'.length);
          } else {
            data['role'] = selected;
            final previous = widget.initial[f.key];
            if (previous is String && previous.startsWith('custom:')) {
              data['access_role_id'] = null;
            }
          }
        } else if (f.kind == 'manager_parent') {
          if (managerSelected && changedSelections.contains(f.key)) {
            data[f.key] = values[f.key] == '' ? null : values[f.key];
          }
        } else if (f.kind == 'multiselect') {
          if (managerSelected && changedSelections.contains(f.key)) {
            data[f.key] = values[f.key];
          }
        } else if (f.kind == 'bool' || f.options != null) {
          if (f.key == 'show_snmp_profiles' &&
              widget.initial.containsKey(f.key) &&
              !changedSelections.contains(f.key)) {
            continue;
          }
          data[f.key] = values[f.key] == '' ? null : values[f.key];
        } else {
          final text = controls[f.key]!.text;
          data[f.key] = text.isEmpty
              ? (f.initial == '' ? '' : null)
              : f.kind == 'int'
              ? int.parse(text)
              : f.kind == 'number'
              ? double.parse(text)
              : text;
        }
      }
      await widget.save(data);
      if (mounted) Navigator.pop(context, data);
    } catch (e) {
      if (mounted) setState(() => error = e.toString());
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => AlertDialog(
    title: Text(widget.title),
    content: SizedBox(
      width: 520,
      child: SingleChildScrollView(
        child: Form(
          key: form,
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              for (final f in widget.fields)
                if (!['multiselect', 'manager_parent'].contains(f.kind) ||
                    managerSelected)
                  Padding(
                    padding: const EdgeInsets.only(bottom: 16),
                    child: f.kind == 'multiselect'
                        ? Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              AppText(
                                f.label,
                                style: const TextStyle(
                                  fontWeight: FontWeight.bold,
                                ),
                              ),
                              const AppText(
                                'Includes all current and future towers in each selected place. Changing this selection replaces previous individual tower assignments.',
                              ),
                              if (f.options!.isEmpty)
                                const AppText('Add places in Towers first.'),
                              for (final option in f.options!)
                                CheckboxListTile(
                                  title: Text(option.label),
                                  contentPadding: EdgeInsets.zero,
                                  controlAffinity:
                                      ListTileControlAffinity.leading,
                                  value: (values[f.key] as List? ?? [])
                                      .contains(option.value),
                                  onChanged: busy
                                      ? null
                                      : (selected) => setState(() {
                                          final selection = List<String>.from(
                                            values[f.key] ?? [],
                                          );
                                          if (selected == true) {
                                            selection.add(option.value);
                                          } else {
                                            selection.remove(option.value);
                                          }
                                          values[f.key] = selection;
                                          changedSelections.add(f.key);
                                        }),
                                ),
                            ],
                          )
                        : f.kind == 'bool'
                        ? SwitchListTile(
                            title: AppText(f.label),
                            value: values[f.key] == true,
                            onChanged: (v) => setState(() {
                              values[f.key] = v;
                              changedSelections.add(f.key);
                            }),
                          )
                        : f.kind == 'snmp_profile'
                        ? snmpProfileField(f)
                        : f.options != null
                        ? DropdownButtonFormField<String>(
                            initialValue:
                                f.options!.any((o) => o.value == values[f.key])
                                ? values[f.key]
                                : null,
                            isExpanded: true,
                            decoration: InputDecoration(
                              labelText: tr(f.label),
                              helperText: f.helperText,
                              helperMaxLines: 4,
                            ),
                            items: f.options!
                                .map(
                                  (o) => DropdownMenuItem(
                                    value: o.value,
                                    child: Text(o.label),
                                  ),
                                )
                                .toList(),
                            validator: (v) =>
                                f.required && (v == null || v.isEmpty)
                                ? 'Required'
                                : null,
                            onChanged: (v) => setState(() {
                              values[f.key] = v;
                              changedSelections.add(f.key);
                              if (f.key == 'vendor') defaultVendorProfile();
                            }),
                          )
                        : TextFormField(
                            controller: controls[f.key],
                            obscureText: f.kind == 'password',
                            decoration: InputDecoration(
                              labelText: tr(f.label),
                              helperText: f.helperText,
                              helperMaxLines: 3,
                            ),
                            validator: (v) {
                              if (f.required && (v == null || v.isEmpty)) {
                                return 'Required';
                              }
                              if (v != null &&
                                  v.isNotEmpty &&
                                  f.kind == 'number' &&
                                  double.tryParse(v) == null) {
                                return 'Enter a number';
                              }
                              if (v != null &&
                                  v.isNotEmpty &&
                                  f.kind == 'int' &&
                                  int.tryParse(v) == null) {
                                return 'Enter an integer';
                              }
                              final number = num.tryParse(v ?? '');
                              if (number != null &&
                                  ((f.min != null && number < f.min!) ||
                                      (f.max != null && number > f.max!))) {
                                return 'Enter a value from ${f.min} to ${f.max}';
                              }
                              return null;
                            },
                          ),
                  ),
              if (error != null) Text(error!, style: TextStyle(color: red)),
            ],
          ),
        ),
      ),
    ),
    actions: [
      TextButton(
        onPressed: busy ? null : () => Navigator.pop(context),
        child: const AppText('Cancel'),
      ),
      FilledButton(
        onPressed: busy ? null : submit,
        child: AppText(busy ? 'Saving…' : 'Save'),
      ),
    ],
  );
}

class NetworkSettings extends StatefulWidget {
  final Api api;
  const NetworkSettings({super.key, required this.api});
  @override
  State<NetworkSettings> createState() => _NetworkSettingsState();
}

class _NetworkSettingsState extends State<NetworkSettings>
    with LanguageRebuild {
  bool get canEdit => canEditSection(widget.api.user ?? {}, 'settings');
  final fields = {
    for (final x in [
      'interface',
      'address',
      'prefix',
      'gateway',
      'dns1',
      'dns2',
      'hostname',
    ])
      x: TextEditingController(),
  };
  String method = 'dhcp';
  String? checkpoint;
  String result = '';
  bool busy = false;
  @override
  void initState() {
    super.initState();
    fields['prefix']!.text = '24';
    fields['hostname']!.text = 'airlink';
    load();
  }

  @override
  void dispose() {
    for (final c in fields.values) {
      c.dispose();
    }
    super.dispose();
  }

  Future<void> load() async {
    try {
      final data = await widget.api.request('/network');
      if (mounted) {
        setState(() {
          result = data['interfaces'].toString();
          checkpoint = data['pending']?['checkpoint'];
        });
      }
    } catch (e) {
      if (mounted) setState(() => result = e.toString());
    }
  }

  Map<String, dynamic> config() => {
    'interface': fields['interface']!.text,
    'method': method,
    'hostname': fields['hostname']!.text,
    if (method == 'static') ...{
      'address': fields['address']!.text,
      'prefix': int.parse(fields['prefix']!.text),
      'gateway': fields['gateway']!.text,
      'dns': [
        fields['dns1']!.text,
        if (fields['dns2']!.text.isNotEmpty) fields['dns2']!.text,
      ],
    },
  };
  Future<void> action(String name) async {
    setState(() => busy = true);
    try {
      final body = ['confirm', 'restore'].contains(name)
          ? {'checkpoint': checkpoint}
          : name == 'test'
          ? {
              'address': fields['gateway']!.text.isEmpty
                  ? '1.1.1.1'
                  : fields['gateway']!.text,
            }
          : name == 'dns'
          ? {'hostname': 'debian.org'}
          : config();
      final data = await widget.api.request(
        '/network/$name',
        method: 'POST',
        body: body,
      );
      if (mounted) {
        setState(() {
          result = jsonEncode(data);
          if (name == 'apply') checkpoint = data['checkpoint'];
          if (['confirm', 'restore'].contains(name)) checkpoint = null;
        });
      }
    } catch (e) {
      if (mounted) setState(() => result = e.toString());
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => Card(
    margin: EdgeInsets.zero,
    child: Padding(
      padding: const EdgeInsets.all(22),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const AppText('Network settings', style: TextStyle(fontSize: 20)),
          const SizedBox(height: 12),
          AppText(
            'Applying settings starts a 120-second rollback timer. Reconnect at the new address and confirm to keep them.',
            style: TextStyle(color: muted),
          ),
          const SizedBox(height: 20),
          DropdownButtonFormField<String>(
            initialValue: method,
            items: const [
              DropdownMenuItem(value: 'dhcp', child: AppText('Automatic DHCP')),
              DropdownMenuItem(
                value: 'static',
                child: AppText('Manual static IPv4'),
              ),
            ],
            onChanged: canEdit ? (v) => setState(() => method = v!) : null,
            decoration: InputDecoration(labelText: tr('Address method')),
          ),
          const SizedBox(height: 16),
          Wrap(
            spacing: 16,
            runSpacing: 16,
            children: [
              for (final key in [
                'interface',
                'hostname',
                if (method == 'static') ...[
                  'address',
                  'prefix',
                  'gateway',
                  'dns1',
                  'dns2',
                ],
              ])
                SizedBox(
                  width: 250,
                  child: TextField(
                    controller: fields[key],
                    readOnly: !canEdit,
                    decoration: InputDecoration(labelText: tr(key)),
                  ),
                ),
            ],
          ),
          const SizedBox(height: 20),
          Wrap(
            spacing: 10,
            runSpacing: 10,
            children: [
              for (final pair in [
                ['save', 'Save settings'],
                ['test', 'Test connection'],
                ['dns', 'Test DNS'],
                ['apply', 'Apply configuration'],
                ['confirm', 'Keep configuration'],
                ['restore', 'Restore previous'],
              ])
                OutlinedButton(
                  onPressed:
                      !canEdit ||
                          busy ||
                          (['confirm', 'restore'].contains(pair[0]) &&
                              checkpoint == null)
                      ? null
                      : () => action(pair[0]),
                  child: Text(pair[1]),
                ),
            ],
          ),
          const SizedBox(height: 16),
          SelectableText(result, style: TextStyle(color: muted)),
        ],
      ),
    ),
  );
}

class HealthBar extends StatelessWidget {
  final int online, offline, unknown;
  const HealthBar({
    super.key,
    required this.online,
    required this.offline,
    required this.unknown,
  });
  @override
  Widget build(BuildContext context) => ClipRRect(
    borderRadius: BorderRadius.circular(6),
    child: SizedBox(
      height: 12,
      child: online + offline + unknown == 0
          ? Container(color: navy)
          : Row(
              children: [
                if (online > 0)
                  Expanded(
                    flex: online,
                    child: Container(color: green),
                  ),
                if (offline > 0)
                  Expanded(
                    flex: offline,
                    child: Container(color: red),
                  ),
                if (unknown > 0)
                  Expanded(
                    flex: unknown,
                    child: Container(color: muted),
                  ),
              ],
            ),
    ),
  );
}

class HistoryChart extends CustomPainter {
  final List<double?> points;
  HistoryChart(this.points) : mode = appThemeMode.value;
  final ThemeMode mode;
  @override
  void paint(Canvas canvas, Size size) {
    final grid = Paint()
      ..color = muted.withValues(alpha: .15)
      ..strokeWidth = 1;
    for (var i = 0; i < 5; i++) {
      final y = size.height * i / 4;
      canvas.drawLine(Offset(0, y), Offset(size.width, y), grid);
    }
    final values = points.whereType<double>().toList();
    if (values.isEmpty) {
      final text = TextPainter(
        text: TextSpan(
          text: 'Bandwidth counters unavailable',
          style: TextStyle(color: muted, fontSize: 14),
        ),
        textDirection: TextDirection.ltr,
      )..layout();
      text.paint(canvas, Offset(16, size.height / 2));
      return;
    }
    final max = values.reduce((a, b) => a > b ? a : b);
    final scale = max > 0 ? max : 1.0;
    final path = Path();
    bool connected = false;
    for (var i = 0; i < points.length; i++) {
      final v = points[i];
      if (v == null) {
        connected = false;
        continue;
      }
      final x = points.length == 1
          ? size.width / 2
          : size.width * i / (points.length - 1);
      final y = size.height - 12 - (size.height - 28) * v / scale;
      if (connected) {
        path.lineTo(x, y);
      } else {
        path.moveTo(x, y);
        connected = true;
      }
      canvas.drawCircle(Offset(x, y), 2, Paint()..color = blue);
    }
    canvas.drawPath(
      path,
      Paint()
        ..color = blue
        ..style = PaintingStyle.stroke
        ..strokeWidth = 2,
    );
    final label = TextPainter(
      text: TextSpan(
        text: '${max.toStringAsFixed(2)} Mbit/s',
        style: TextStyle(color: muted, fontSize: 11),
      ),
      textDirection: TextDirection.ltr,
    )..layout();
    label.paint(canvas, const Offset(4, 0));
  }

  @override
  bool shouldRepaint(covariant HistoryChart oldDelegate) =>
      oldDelegate.points != points || oldDelegate.mode != mode;
}
