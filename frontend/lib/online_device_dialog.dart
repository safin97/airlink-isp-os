import 'package:flutter/material.dart';
import 'api.dart';
import 'online_device_dashboard.dart';
import 'tower_device_panel.dart';
import 'tower_api_login.dart';
import 'app_language.dart';
import 'device_login_profiles.dart';
import 'section_access.dart';
import 'package:url_launcher/url_launcher.dart';

class OnlineDeviceDialog extends StatefulWidget {
  final Api api;
  final Map<String, dynamic> row;
  final String? towerDeviceId;
  const OnlineDeviceDialog({
    super.key,
    required this.api,
    required this.row,
    this.towerDeviceId,
  });

  @override
  State<OnlineDeviceDialog> createState() => _OnlineDeviceDialogState();
}

class _OnlineDeviceDialogState extends State<OnlineDeviceDialog> {
  Map<String, dynamic>? data;
  String? error;
  bool busy = true;
  bool loadingProfiles = true, profilesLoaded = false;
  int? loginErrorStatus;
  bool showDetails = false;
  List<dynamic> profiles = [];
  late String profileId = widget.towerDeviceId == null ? 'auto' : '';
  bool get towerLogin => widget.towerDeviceId != null;
  String? resolvedProfileId, attemptLabel;
  bool hasDefaultLogin = false;
  final loginUsername = TextEditingController();
  final loginPassword = TextEditingController();
  final ssids = <String, TextEditingController>{};
  String? fingerprint, message;
  bool mustReload = false;
  bool get canEdit =>
      !towerLogin && canEditSection(widget.api.user ?? {}, 'isp_card');

  @override
  void dispose() {
    loginUsername.dispose();
    loginPassword.dispose();
    for (final controller in ssids.values) {
      controller.dispose();
    }
    super.dispose();
  }

  void resetConnection() {
    setState(() {
      data = null;
      resolvedProfileId = null;
      attemptLabel = null;
      error = null;
      loginErrorStatus = null;
      message = null;
      fingerprint = null;
      mustReload = false;
    });
  }

  String radioKey(Map radio) => '${radio['menu']}:${radio['id']}';

  Map<String, dynamic> payload({String? candidate}) {
    final selected = profileId == 'manual'
        ? 'manual'
        : candidate ?? resolvedProfileId;
    if (selected == null) throw StateError('Connect to a device first.');
    if (towerLogin) return {'profile_id': selected};
    return {
      'username': '${widget.row['username']}',
      'ip_address': '${widget.row['ip_address']}',
      if (widget.row['session_id'] != null)
        'session_id': '${widget.row['session_id']}',
      if (fingerprint != null) 'ssh_fingerprint': fingerprint,
      if (selected == 'online') 'use_online_login': true,
      if (selected != 'manual' && selected != 'online') 'profile_id': selected,
      if (selected == 'manual')
        'login': {
          'username': loginUsername.text.trim(),
          'password': loginPassword.text,
          'transport': 'auto',
          'protocol': 'both',
          'verify_tls': true,
          if (fingerprint != null) 'ssh_fingerprint': fingerprint,
        },
    };
  }

  Future<void> saveRadio(Map radio) async {
    if (!canEdit) return;
    setState(() {
      busy = true;
      error = null;
      message = null;
    });
    try {
      final result = await widget.api.request(
        '/integrations/sas4/online-device/settings',
        method: 'PUT',
        body: {
          ...payload(),
          if (data?['connection'] != null) 'connection': data!['connection'],
          'change': {
            'menu': radio['menu'],
            'radio_id': radio['id'],
            'previous_ssid': radio['ssid'],
            'ssid': ssids[radioKey(radio)]!.text,
          },
          'restart_radio': data?['restart_on_save'] == true,
        },
      );
      if (!mounted) {
        return;
      }
      setState(() {
        mustReload = true;
        message = result['status'] == 'restarting'
            ? 'Settings saved. Radio restart requested. Reconnect after it comes online.'
            : 'Device accepted the change. Refresh to verify the new settings.';
      });
    } catch (e) {
      if (mounted) {
        setState(() {
          error = e.toString();
          mustReload = true;
        });
      }
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> saveTowerSettings(Map<String, dynamic> change) async {
    setState(() {
      busy = true;
      error = null;
      message = null;
      mustReload = true;
    });
    try {
      await widget.api.request(
        '/devices/${Uri.encodeComponent(widget.towerDeviceId!)}/settings',
        method: 'PUT',
        body: {...payload(), ...change},
      );
      if (!mounted) return;
      await load();
      if (mounted && error == null) {
        setState(
          () => message = 'Device accepted the change. Settings refreshed.',
        );
      }
    } catch (e) {
      if (mounted) setState(() => error = e.toString());
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  @override
  void initState() {
    super.initState();
    loadProfiles();
  }

  Future<void> loadProfiles() async {
    setState(() {
      busy = true;
      loadingProfiles = true;
      profilesLoaded = false;
      error = null;
      loginErrorStatus = null;
    });
    try {
      final result = await widget.api.request(
        towerLogin
            ? '/devices/${Uri.encodeComponent(widget.towerDeviceId!)}/login-profiles'
            : deviceLoginProfilesPath,
      );
      final defaults = towerLogin
          ? <String, dynamic>{}
          : await widget.api.request('/integrations/sas4/device-access');
      if (mounted) {
        setState(() {
          profiles = (result as List)
              .where((p) => p['enabled'] == true)
              .toList();
          profilesLoaded = true;
          if (towerLogin && !profiles.any((p) => p['id'] == profileId)) {
            profileId = '';
          }
          hasDefaultLogin =
              defaults['enabled'] != false &&
              defaults['has_api_password'] == true &&
              '${defaults['api_username'] ?? ''}'.isNotEmpty;
        });
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          error = e.toString();
          loginErrorStatus = e is ApiException ? e.status : null;
        });
      }
    } finally {
      if (mounted) {
        setState(() {
          busy = false;
          loadingProfiles = false;
        });
      }
    }
  }

  Future<void> addTowerProfile() async {
    if (widget.api.user?['role'] != 'owner' || busy) return;
    final saved = await showDialog<bool>(
      context: context,
      builder: (_) => DeviceLoginProfileEditor(
        api: widget.api,
        path: towersApiProfilesPath,
      ),
    );
    if (saved == true && mounted) await loadProfiles();
  }

  Future<dynamic> connectCandidate(String candidate) async {
    Future<dynamic> connect() => widget.api.request(
      towerLogin
          ? '/devices/${Uri.encodeComponent(widget.towerDeviceId!)}/login'
          : '/integrations/sas4/online-device/login',
      method: 'POST',
      body: payload(candidate: candidate),
    );
    var result = await connect();
    if (!mounted) throw StateError('Device panel closed.');
    final offered = result['requires_trust'] == true
        ? result['ssh_fingerprint']
        : result['ssh_upgrade_fingerprint'];
    if (result['requires_trust'] == true || offered != null) {
      if (offered is! String ||
          !RegExp(r'^SHA256:[A-Za-z0-9+/]{43}$').hasMatch(offered)) {
        throw StateError('The device did not return a valid SSH key.');
      }
      if (fingerprint != null && fingerprint != offered) {
        throw StateError('SSH host key changed. Connection stopped.');
      }
      if (fingerprint == null) {
        // Trust the first key for this login panel, then pin every subsequent request.
        fingerprint = offered;
        result = await connect();
        if (!mounted) throw StateError('Device panel closed.');
      }
      if (result['requires_trust'] == true) {
        throw StateError('SSH key verification failed. Connection stopped.');
      }
      final nextKey = result['ssh_upgrade_fingerprint'];
      if (nextKey != null && nextKey != fingerprint) {
        throw StateError('SSH host key changed. Connection stopped.');
      }
    }
    return result;
  }

  Future<void> load() async {
    if (towerLogin && profileId.isEmpty) {
      setState(() => error = 'Choose a saved login from Towers API.');
      return;
    }
    if (profileId == 'manual' &&
        (loginUsername.text.trim().isEmpty || loginPassword.text.isEmpty)) {
      setState(() => error = 'Enter the device username and password.');
      return;
    }
    setState(() {
      busy = true;
      error = null;
      loginErrorStatus = null;
    });
    try {
      final candidates = profileId == 'manual'
          ? ['manual']
          : profileId == 'auto'
          ? <String>[
              if (hasDefaultLogin) 'online',
              for (final profile in profiles) '${profile['id']}',
            ]
          : [profileId];
      if (candidates.isEmpty) {
        throw StateError(
          'Add a username and password in Device login in the sidebar, or enter them manually.',
        );
      }
      // Refresh the successful login first; saves always use that same login.
      if (resolvedProfileId != null && candidates.remove(resolvedProfileId)) {
        candidates.insert(0, resolvedProfileId!);
      }
      dynamic result;
      String? matched;
      Object? lastError;
      for (var index = 0; index < candidates.length; index++) {
        if (!mounted) return;
        setState(
          () => attemptLabel = profileId == 'auto'
              ? 'Trying saved login ${index + 1} of ${candidates.length}…'
              : null,
        );
        try {
          result = await connectCandidate(candidates[index]);
          matched = candidates[index];
          break;
        } on ApiException catch (e) {
          // Only credential rejection/unavailable services may advance to another login.
          // Session, permission and SSH-key conflicts stop immediately.
          if (profileId != 'auto' || (e.status != 502 && e.status != 504)) {
            rethrow;
          }
          lastError = e;
        }
      }
      if (!mounted) return;
      if (matched == null) {
        throw StateError('No saved device login connected. ${lastError ?? ''}');
      }
      resolvedProfileId = matched;
      for (final radio in result['settings'] as List? ?? []) {
        ssids.putIfAbsent(radioKey(radio), () => TextEditingController()).text =
            radio['ssid'] ?? '';
      }
      setState(() {
        data = Map<String, dynamic>.from(result);
        mustReload = false;
        message = null;
      });
    } catch (e) {
      if (mounted) {
        setState(() {
          error = e.toString();
          loginErrorStatus = e is ApiException ? e.status : null;
        });
      }
    } finally {
      if (mounted) {
        setState(() {
          busy = false;
          attemptLabel = null;
        });
      }
    }
  }

  String value(dynamic item, [String suffix = '']) =>
      item == null || '$item'.isEmpty ? tr('Unavailable') : '$item$suffix';

  Widget section(
    String title,
    List<dynamic> rows,
    List<String> labels,
    List<String> Function(dynamic) cells,
    String empty,
  ) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            AppText(title, style: Theme.of(context).textTheme.titleMedium),
            const SizedBox(height: 8),
            if (rows.isEmpty)
              AppText(empty)
            else
              SingleChildScrollView(
                scrollDirection: Axis.horizontal,
                child: DataTable(
                  horizontalMargin: 0,
                  columnSpacing: 24,
                  columns: [
                    for (final label in labels)
                      DataColumn(label: AppText(label)),
                  ],
                  rows: [
                    for (final row in rows)
                      DataRow(
                        cells: [
                          for (final text in cells(row))
                            DataCell(SelectableText(text)),
                        ],
                      ),
                  ],
                ),
              ),
          ],
        ),
      ),
    );
  }

  Widget connectedDetails() => Column(
    crossAxisAlignment: CrossAxisAlignment.stretch,
    children: [
      Text(
        '${data!['device_type'] ?? data!['vendor']} • ${tr('Login')}: ${data!['credential_source']}',
      ),
      if (data!['connection_attempts'] != null)
        ExpansionTile(
          title: const AppText('Connection attempts'),
          children: [
            for (final attempt in data!['connection_attempts'])
              ListTile(
                dense: true,
                title: Text('${attempt['connection']}'),
                trailing: Text('${attempt['status']}'),
              ),
          ],
        ),
      TextButton.icon(
        onPressed: () => launchUrl(
          Uri.parse(
            data!['web_url'] ??
                'http://${widget.row['ip_address'].toString().contains(':') ? '[${widget.row['ip_address']}]' : widget.row['ip_address']}',
          ),
          mode: LaunchMode.externalApplication,
        ),
        icon: const Icon(Icons.open_in_new),
        label: const AppText('Open full device interface'),
      ),
      if (data!['settings_note'] != null) Text(data!['settings_note']),
      for (final group in (data!['groups'] as Map? ?? {}).entries)
        Card(
          child: ExpansionTile(
            title: Text('${group.key}'),
            children: [
              for (final row in group.value as List)
                Padding(
                  padding: const EdgeInsets.all(12),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      for (final entry in (row as Map).entries)
                        SelectableText('${entry.key}: ${value(entry.value)}'),
                    ],
                  ),
                ),
            ],
          ),
        ),
      if ((data!['settings'] as List? ?? []).isNotEmpty)
        Card(
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const AppText(
                  'Wireless settings',
                  style: TextStyle(fontWeight: FontWeight.bold),
                ),
                if (!canEdit)
                  AppText(
                    towerLogin
                        ? 'This API overview is read-only. Use Manage device in Towers for wireless changes.'
                        : 'Read-only access. ISP Card edit permission is required to save.',
                  ),
                for (final radio in data!['settings']) ...[
                  TextField(
                    controller: ssids[radioKey(radio)],
                    enabled:
                        !busy &&
                        !mustReload &&
                        canEdit &&
                        radio['editable'] == true,
                    decoration: InputDecoration(
                      labelText: '${radio['name']} SSID',
                    ),
                    onChanged: (_) => setState(() {}),
                  ),
                  if (radio['editable'] != true)
                    const AppText(
                      'This SSID is inherited or controlled by a controller.',
                    ),
                  if (canEdit && radio['editable'] == true) ...[
                    const AppText(
                      'Changing SSID disconnects wireless clients.',
                    ),
                    TextButton(
                      onPressed:
                          busy ||
                              mustReload ||
                              ssids[radioKey(radio)]!.text == radio['ssid']
                          ? null
                          : () => saveRadio(Map<String, dynamic>.from(radio)),
                      child: AppText(
                        data!['restart_on_save'] == true
                            ? 'Save SSID and restart radio'
                            : 'Save SSID',
                      ),
                    ),
                  ],
                ],
              ],
            ),
          ),
        ),
      section(
        'Registered clients',
        data!['registrations'] as List? ?? [],
        ['Interface', 'MAC address', 'Signal', 'TX rate', 'RX rate'],
        (r) => [
          value(r['interface']),
          value(r['mac-address'] ?? r['mac_address']),
          value(r['signal-strength'] ?? r['signal'] ?? r['signal_dbm']),
          value(r['tx-rate']),
          value(r['rx-rate']),
        ],
        'No registered clients reported.',
      ),
      section(
        'Wireless',
        data!['wireless'] as List? ?? [],
        ['Interface', 'SSID', 'Signal', 'Status'],
        (r) => [
          value(r['name']),
          value(r['ssid']),
          value(r['signal_dbm'], ' dBm'),
          value(r['status']),
        ],
        'No wireless readings available.',
      ),
      section(
        'Ethernet ports',
        data!['ethernet'] as List? ?? [],
        ['Port', 'Status', 'Speed'],
        (r) => [
          value(r['name']),
          value(r['status']),
          value(r['speed_mbps'], ' Mbps'),
        ],
        'No Ethernet readings available.',
      ),
      section(
        'PPPoE',
        data!['pppoe'] as List? ?? [],
        [
          'Name',
          'Username',
          'Interface',
          'Status',
          'Uptime',
          'Local IP',
          'Remote IP',
        ],
        (r) => [
          value(r['name']),
          value(r['username']),
          value(r['interface']),
          value(r['status']),
          value(r['uptime']),
          value(r['local-address']),
          value(r['remote-address']),
        ],
        data!['pppoe_note']?.toString() ??
            'No PPPoE client interfaces configured.',
      ),
      TextButton(
        onPressed: busy ? null : resetConnection,
        child: const AppText('Change device login'),
      ),
    ],
  );

  @override
  Widget build(BuildContext context) => PopScope(
    canPop: !busy,
    child: data != null && towerLogin && data!['tower_settings'] != null
        ? TowerDevicePanel(
            data: data!,
            busy: busy,
            stale: error != null || mustReload,
            canEdit: canEditSection(widget.api.user ?? {}, 'towers'),
            error: error,
            message: message,
            onRefresh: load,
            onSave: saveTowerSettings,
            onClose: () => Navigator.pop(context),
            onChangeLogin: resetConnection,
          )
        : data != null
        ? OnlineDeviceDashboard(
            data: data!,
            row: widget.row,
            busy: busy,
            stale: error != null || mustReload,
            showDetails: showDetails,
            showSubscription: !towerLogin,
            error: error,
            message: message,
            onRefresh: busy ? null : load,
            onClose: busy ? null : () => Navigator.pop(context),
            onSettings: () => setState(() => showDetails = !showDetails),
            details: connectedDetails(),
          )
        : towerLogin
        ? TowerApiLogin(
            device: widget.row,
            profiles: profiles,
            profileId: profileId,
            busy: busy,
            loadingProfiles: loadingProfiles,
            profilesLoaded: profilesLoaded,
            owner: widget.api.user?['role'] == 'owner',
            canEdit: canEditSection(widget.api.user ?? {}, 'towers'),
            error: error,
            errorStatus: loginErrorStatus,
            onSelect: (id) {
              setState(() => profileId = id);
              resetConnection();
            },
            onConnect: load,
            onReload: loadProfiles,
            onClose: () => Navigator.pop(context),
            onAddProfile: addTowerProfile,
          )
        : AlertDialog(
            title: AppText('Device • ${widget.row['username']}'),
            content: SizedBox(
              width: 860,
              child: SingleChildScrollView(
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    SelectableText('${widget.row['ip_address']}'),
                    const SizedBox(height: 16),
                    DropdownButtonFormField<String>(
                      key: ValueKey('login-profile-$profileId'),
                      initialValue: profileId,
                      isExpanded: true,
                      decoration: const InputDecoration(
                        labelText: 'Device login profile',
                      ),
                      items: [
                        const DropdownMenuItem(
                          value: 'auto',
                          child: Text('Automatic — try saved logins'),
                        ),
                        if (hasDefaultLogin)
                          const DropdownMenuItem(
                            value: 'online',
                            child: Text('Default online-user device login'),
                          ),
                        for (final profile in profiles)
                          DropdownMenuItem(
                            value: '${profile['id']}',
                            child: Text(
                              '${profile['name']} — ${profile['username']}',
                            ),
                          ),
                        const DropdownMenuItem(
                          value: 'manual',
                          child: Text('Temporary username and password'),
                        ),
                      ],
                      onChanged: busy
                          ? null
                          : (value) => setState(() {
                              profileId = value!;
                              resetConnection();
                            }),
                    ),
                    if (profileId == 'manual') ...[
                      const SizedBox(height: 12),
                      TextField(
                        key: const ValueKey('device-username'),
                        controller: loginUsername,
                        enabled: !busy,
                        decoration: const InputDecoration(
                          labelText: 'Device username',
                        ),
                        onChanged: (_) => resetConnection(),
                      ),
                      TextField(
                        key: const ValueKey('device-password'),
                        controller: loginPassword,
                        enabled: !busy,
                        obscureText: true,
                        enableSuggestions: false,
                        autocorrect: false,
                        decoration: const InputDecoration(
                          labelText: 'Device password',
                        ),
                        onChanged: (_) => resetConnection(),
                      ),
                      const AppText(
                        'Temporary login. Credentials are cleared when this panel closes.',
                      ),
                    ],

                    if (busy) ...[
                      const SizedBox(height: 12),
                      const LinearProgressIndicator(),
                      AppText(
                        attemptLabel ??
                            'Detecting device and trying connections one by one…',
                      ),
                    ],
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
                  ],
                ),
              ),
            ),
            actions: [
              TextButton(
                onPressed: busy ? null : load,
                child: AppText(data == null ? 'Connect' : 'Refresh'),
              ),
              TextButton(
                onPressed: busy ? null : () => Navigator.pop(context),
                child: const AppText('Close'),
              ),
            ],
          ),
  );
}
