import 'package:flutter/material.dart';
import 'api.dart';
import 'app_language.dart';

class DeviceApiAccessPanel extends StatefulWidget {
  const DeviceApiAccessPanel({
    super.key,
    required this.api,
    this.initiallyExpanded = false,
  });
  final Api api;
  final bool initiallyExpanded;
  @override
  State<DeviceApiAccessPanel> createState() => _DeviceApiAccessPanelState();
}

class _DeviceApiAccessPanelState extends State<DeviceApiAccessPanel> {
  final username = TextEditingController(),
      password = TextEditingController(),
      port = TextEditingController();
  List<dynamic> towers = [], managers = [], savedManagers = [];
  String scope = 'tower', protocol = 'https';
  String? target, error, message;
  bool busy = true, enabled = true, verifyTls = true, hasPassword = false;
  @override
  void initState() {
    super.initState();
    load();
  }

  @override
  void dispose() {
    username.dispose();
    password.dispose();
    port.dispose();
    super.dispose();
  }

  Future<void> load() async {
    try {
      final data = await widget.api.request('/device-api-access');
      if (mounted) {
        setState(() {
          towers = data['towers'];
          savedManagers = data['isp_managers'];
        });
      }
    } catch (e) {
      if (mounted) setState(() => error = e.toString());
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  void select(String? id) {
    final options = scope == 'tower' ? towers : savedManagers;
    final found = options
        .where((row) => row['id'].toString() == id)
        .firstOrNull;
    setState(() {
      target = id;
      username.text = found?['username'] ?? '';
      password.clear();
      hasPassword = found?['has_password'] == true;
      protocol = found?['protocol'] ?? 'https';
      port.text = found?['port']?.toString() ?? '';
      enabled = hasPassword ? (found?['enabled'] ?? true) : true;
      verifyTls = found?['verify_tls'] ?? true;
      message = null;
      error = null;
    });
  }

  Future<void> changeScope(String value) async {
    setState(() => scope = value);
    select(null);
    if (value != 'isp_manager') return;
    setState(() => busy = true);
    try {
      final data = await widget.api.request(
        '/integrations/sas4/reports/managers',
      );
      if (mounted) {
        setState(
          () => managers = (data as List)
              .map(
                (row) => {'id': row['id'].toString(), 'name': row['username']},
              )
              .toList(),
        );
      }
    } catch (e) {
      if (mounted) setState(() => error = e.toString());
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> save() async {
    final parsedPort = port.text.isEmpty ? null : int.tryParse(port.text);
    if (target == null ||
        username.text.trim().isEmpty ||
        (!hasPassword && password.text.isEmpty) ||
        (port.text.isNotEmpty &&
            (parsedPort == null || parsedPort < 1 || parsedPort > 65535))) {
      setState(
        () =>
            error = 'Choose a target, enter its device login and a valid port.',
      );
      return;
    }
    setState(() {
      busy = true;
      error = null;
      message = null;
    });
    try {
      final data = await widget.api.request(
        '/device-api-access',
        method: 'PUT',
        body: {
          'scope': scope,
          'target_id': target,
          'username': username.text,
          'password': password.text.isEmpty ? null : password.text,
          'protocol': protocol,
          'port': parsedPort,
          'verify_tls': verifyTls,
          'enabled': enabled,
        },
      );
      if (mounted) {
        setState(() {
          final rows = scope == 'tower' ? towers : savedManagers;
          final row = rows
              .where((r) => r['id'].toString() == target)
              .firstOrNull;
          if (row != null) {
            row.addAll(data as Map);
          } else {
            rows.add({'id': target, ...Map<String, dynamic>.from(data)});
          }
          hasPassword = data['has_password'] == true;
          password.clear();
          message =
              'Device API login saved for the selected ${scope == 'tower' ? 'tower' : 'ISP Card manager'}.';
        });
      }
    } catch (e) {
      if (mounted) setState(() => error = e.toString());
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => ExpansionTile(
    initiallyExpanded: widget.initiallyExpanded,
    title: const AppText('Device API logins'),
    subtitle: const AppText(
      'Assign device credentials to a tower or ISP Card manager',
    ),
    children: [
      Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            DropdownButtonFormField<String>(
              initialValue: scope,
              decoration: const InputDecoration(labelText: 'Assign to'),
              items: const [
                DropdownMenuItem(value: 'tower', child: Text('Tower')),
                DropdownMenuItem(
                  value: 'isp_manager',
                  child: Text('ISP Card manager'),
                ),
              ],
              onChanged: busy ? null : (v) => changeScope(v!),
            ),
            const SizedBox(height: 12),
            DropdownButtonFormField<String>(
              key: ValueKey('device-api-target-$scope-$target'),
              initialValue: target,
              isExpanded: true,
              decoration: InputDecoration(
                labelText: scope == 'tower'
                    ? 'Choose tower'
                    : 'Choose SAS4 manager',
              ),
              items: (scope == 'tower' ? towers : managers)
                  .map(
                    (row) => DropdownMenuItem<String>(
                      value: row['id'].toString(),
                      child: Text(row['name'], overflow: TextOverflow.ellipsis),
                    ),
                  )
                  .toList(),
              onChanged: busy ? null : select,
            ),
            TextField(
              key: const ValueKey('device-api-username'),
              controller: username,
              enabled: !busy && target != null,
              decoration: const InputDecoration(labelText: 'Device username'),
              autocorrect: false,
              enableSuggestions: false,
            ),
            TextField(
              key: const ValueKey('device-api-password'),
              controller: password,
              enabled: !busy && target != null,
              obscureText: true,
              decoration: InputDecoration(
                labelText: 'Device password',
                helperText: hasPassword
                    ? 'Leave blank to keep the saved password.'
                    : 'Enter the device login password.',
              ),
              autocorrect: false,
              enableSuggestions: false,
            ),
            const SizedBox(height: 12),
            DropdownButtonFormField<String>(
              key: ValueKey('device-api-protocol-$scope-$target-$protocol'),
              initialValue: protocol,
              decoration: const InputDecoration(labelText: 'Connection'),
              items: const [
                DropdownMenuItem(value: 'https', child: Text('HTTPS')),
                DropdownMenuItem(value: 'http', child: Text('HTTP')),
                DropdownMenuItem(
                  value: 'both',
                  child: Text('HTTPS + HTTP (auto)'),
                ),
              ],
              onChanged: busy ? null : (v) => setState(() => protocol = v!),
            ),
            TextField(
              controller: port,
              enabled: !busy && target != null,
              keyboardType: TextInputType.number,
              decoration: const InputDecoration(
                labelText: 'Port (blank uses 443 / 80)',
                helperText:
                    'HTTPS + HTTP tries HTTPS first, then unencrypted HTTP if unavailable. A custom port applies to both.',
                helperMaxLines: 3,
              ),
            ),
            SwitchListTile(
              contentPadding: EdgeInsets.zero,
              title: const AppText('Verify HTTPS certificate'),
              value: verifyTls,
              onChanged: busy ? null : (v) => setState(() => verifyTls = v),
            ),
            SwitchListTile(
              contentPadding: EdgeInsets.zero,
              title: const AppText('Enable device API access'),
              value: enabled,
              onChanged: busy ? null : (v) => setState(() => enabled = v),
            ),
            const AppText(
              'Passwords are encrypted and never displayed. These are device logins, separate from SAS4 account passwords. ISP Card automatic readings continue using SNMP.',
            ),
            if (busy) const LinearProgressIndicator(),
            if (error != null)
              Text(
                error!,
                style: TextStyle(color: Theme.of(context).colorScheme.error),
              ),
            if (message != null) Text(message!),
            FilledButton(
              onPressed: busy || target == null ? null : save,
              child: const AppText('Save device login'),
            ),
          ],
        ),
      ),
    ],
  );
}
