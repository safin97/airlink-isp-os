import 'package:flutter/material.dart';
import 'api.dart';
import 'app_language.dart';
import 'device_login_profiles.dart';
import 'section_access.dart';
import 'package:url_launcher/url_launcher.dart';

class OnlineDeviceDialog extends StatefulWidget {
  final Api api;
  final Map<String, dynamic> row;
  const OnlineDeviceDialog({super.key, required this.api, required this.row});

  @override
  State<OnlineDeviceDialog> createState() => _OnlineDeviceDialogState();
}

class _OnlineDeviceDialogState extends State<OnlineDeviceDialog> {
  Map<String, dynamic>? data;
  String? error;
  bool busy = true;
  List<dynamic> profiles = [];
  String profileId = 'manual';
  final loginUsername = TextEditingController();
  final loginPassword = TextEditingController();
  final port = TextEditingController();
  final community = TextEditingController(text: 'public');
  final ssids = <String, TextEditingController>{};
  String transport = 'auto', protocol = 'both';
  String? fingerprint, pendingFingerprint, message;
  bool verifyTls = true, mustReload = false;
  bool get canEdit => canEditSection(widget.api.user ?? {}, 'isp_card');

  @override
  void dispose() {
    loginUsername.dispose();
    loginPassword.dispose();
    port.dispose();
    community.dispose();
    for (final controller in ssids.values) {
      controller.dispose();
    }
    super.dispose();
  }

  void resetConnection() {
    setState(() {
      data = null;
      error = null;
      message = null;
      fingerprint = null;
      pendingFingerprint = null;
      mustReload = false;
    });
  }

  String radioKey(Map radio) => '${radio['menu']}:${radio['id']}';

  Map<String, dynamic> payload() => {
    'username': '${widget.row['username']}',
    'ip_address': '${widget.row['ip_address']}',
    if (widget.row['session_id'] != null)
      'session_id': '${widget.row['session_id']}',
    if (fingerprint != null) 'ssh_fingerprint': fingerprint,
    if (profileId != '' && profileId != 'manual') 'profile_id': profileId,
    if (profileId == 'manual')
      'login': {
        'username': loginUsername.text.trim(),
        'password': loginPassword.text,
        'transport': transport,
        'snmp_community': community.text,
        'protocol': protocol,
        'verify_tls': verifyTls,
        if (port.text.trim().isNotEmpty) 'port': int.parse(port.text.trim()),
        if (fingerprint != null) 'ssh_fingerprint': fingerprint,
      },
  };

  Future<void> saveRadio(Map radio) async {
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

  @override
  void initState() {
    super.initState();
    loadProfiles();
  }

  Future<void> loadProfiles() async {
    setState(() {
      busy = true;
      error = null;
    });
    try {
      final result = await widget.api.request(deviceLoginProfilesPath);
      if (mounted) {
        setState(() {
          profiles = (result as List)
              .where((p) => p['enabled'] == true)
              .toList();
          if (profileId.isNotEmpty &&
              profileId != 'manual' &&
              !profiles.any((p) => p['id'] == profileId)) {
            profileId = '';
            data = null;
          }
        });
      }
    } catch (e) {
      if (mounted) {
        setState(() => error = e.toString());
      }
    } finally {
      if (mounted) {
        setState(() => busy = false);
      }
    }
  }

  Future<void> load() async {
    if (profileId == 'manual' &&
        (loginUsername.text.trim().isEmpty || loginPassword.text.isEmpty)) {
      setState(() => error = 'Enter the device username and password.');
      return;
    }
    final portNumber = int.tryParse(port.text.trim());
    if (profileId == 'manual' &&
        port.text.trim().isNotEmpty &&
        (portNumber == null || portNumber < 1 || portNumber > 65535)) {
      setState(() => error = 'Port must be between 1 and 65535.');
      return;
    }
    setState(() {
      busy = true;
      error = null;
    });
    try {
      final result = await widget.api.request(
        '/integrations/sas4/online-device/login',
        method: 'POST',
        body: payload(),
      );
      if (mounted) {
        if (result['requires_trust'] == true) {
          setState(() {
            pendingFingerprint = result['ssh_fingerprint'];
            data = null;
          });
        } else {
          for (final radio in result['settings'] as List? ?? []) {
            ssids
                    .putIfAbsent(radioKey(radio), () => TextEditingController())
                    .text =
                radio['ssid'] ?? '';
          }
          setState(() {
            data = Map<String, dynamic>.from(result);
            mustReload = false;
            message = null;
            pendingFingerprint = result['ssh_upgrade_fingerprint'];
          });
        }
      }
    } catch (e) {
      if (mounted) {
        setState(() => error = e.toString());
      }
    } finally {
      if (mounted) {
        setState(() => busy = false);
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

  @override
  Widget build(BuildContext context) => PopScope(
    canPop: !busy,
    child: AlertDialog(
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
                    value: 'manual',
                    child: Text('Enter device username and password'),
                  ),
                  const DropdownMenuItem(
                    value: '',
                    child: Text('Automatic — SAS4 manager login'),
                  ),
                  for (final profile in profiles)
                    DropdownMenuItem(
                      value: profile['id'],
                      child: Text(
                        '${profile['name']} (${profile['username']})',
                      ),
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
                const SizedBox(height: 12),
                DropdownButtonFormField<String>(
                  key: const ValueKey('device-transport'),
                  initialValue: transport,
                  decoration: const InputDecoration(
                    labelText: 'Connection type',
                  ),
                  items: const [
                    DropdownMenuItem(
                      value: 'auto',
                      child: Text('Automatic — detect and try connections'),
                    ),
                    DropdownMenuItem(
                      value: 'web',
                      child: Text('Web API — MikroTik REST / Ubiquiti airOS'),
                    ),
                    DropdownMenuItem(
                      value: 'routeros_tls',
                      child: Text('MikroTik RouterOS 6 / 7 — API-SSL (8729)'),
                    ),
                    DropdownMenuItem(
                      value: 'routeros',
                      child: Text('MikroTik RouterOS 6 / 7 — API (8728)'),
                    ),
                    DropdownMenuItem(
                      value: 'airos_ssh',
                      child: Text('Ubiquiti M5 / AC — SSH (22)'),
                    ),
                  ],
                  onChanged: busy
                      ? null
                      : (v) {
                          transport = v!;
                          port.clear();
                          resetConnection();
                        },
                ),
                if (transport == 'auto')
                  TextField(
                    controller: community,
                    enabled: !busy,
                    obscureText: true,
                    decoration: const InputDecoration(
                      labelText: 'SNMP read community (v1 / v2)',
                    ),
                    onChanged: (_) => resetConnection(),
                  ),
                if (transport == 'web')
                  DropdownButtonFormField<String>(
                    initialValue: protocol,
                    decoration: const InputDecoration(
                      labelText: 'Web connection',
                    ),
                    items: const [
                      DropdownMenuItem(
                        value: 'both',
                        child: Text('HTTPS + HTTP'),
                      ),
                      DropdownMenuItem(value: 'https', child: Text('HTTPS')),
                      DropdownMenuItem(value: 'http', child: Text('HTTP')),
                    ],
                    onChanged: busy
                        ? null
                        : (v) {
                            protocol = v!;
                            resetConnection();
                          },
                  ),
                TextField(
                  controller: port,
                  enabled: !busy,
                  keyboardType: TextInputType.number,
                  decoration: InputDecoration(
                    labelText: transport == 'auto'
                        ? 'Web port (blank for default)'
                        : 'Port (blank for default)',
                  ),
                  onChanged: (_) => resetConnection(),
                ),
                if (transport == 'auto' ||
                    transport == 'web' ||
                    transport == 'routeros_tls')
                  CheckboxListTile(
                    contentPadding: EdgeInsets.zero,
                    title: const AppText('Verify device TLS certificate'),
                    value: verifyTls,
                    onChanged: busy
                        ? null
                        : (v) {
                            verifyTls = v!;
                            resetConnection();
                          },
                  ),
              ],
              if (pendingFingerprint != null) ...[
                const AppText(
                  'Verify this SSH fingerprint against your device before connecting:',
                ),
                SelectableText(pendingFingerprint!),
                TextButton(
                  onPressed: busy
                      ? null
                      : () {
                          fingerprint = pendingFingerprint;
                          load();
                        },
                  child: const AppText('Trust this SSH key and connect'),
                ),
              ],
              TextButton(
                onPressed: busy ? null : loadProfiles,
                child: const AppText('Reload profiles'),
              ),
              if (busy) ...[
                const SizedBox(height: 12),
                const LinearProgressIndicator(),
                AppText(
                  transport == 'auto' || profileId != 'manual'
                      ? 'Detecting device and trying connections one by one…'
                      : 'Connecting…',
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
              if (data != null) ...[
                Text(
                  '${data!['device_type'] ?? data!['vendor']} • ${tr('Login')}: ${data!['credential_source']}',
                ),
                if (data!['snmp_version'] != null)
                  Text('Detected with SNMP v${data!['snmp_version']}'),
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
                if (error != null)
                  const AppText('Showing the previous readings.'),
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
                if (data!['settings_note'] != null)
                  Text(data!['settings_note']),
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
                                  SelectableText(
                                    '${entry.key}: ${value(entry.value)}',
                                  ),
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
                            const AppText(
                              'Read-only access. ISP Card edit permission is required to save.',
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
                                        ssids[radioKey(radio)]!.text ==
                                            radio['ssid']
                                    ? null
                                    : () => saveRadio(
                                        Map<String, dynamic>.from(radio),
                                      ),
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
                    value(
                      r['signal-strength'] ?? r['signal'] ?? r['signal_dbm'],
                    ),
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
              ],
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
