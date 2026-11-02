import 'package:flutter/material.dart';
import 'api.dart';
import 'section_access.dart';
import 'app_language.dart';

class CustomerDeviceAccess extends StatefulWidget {
  const CustomerDeviceAccess({super.key, required this.api});
  final Api api;
  @override
  State<CustomerDeviceAccess> createState() => _CustomerDeviceAccessState();
}

class _CustomerDeviceAccessState extends State<CustomerDeviceAccess>
    with LanguageRebuild {
  bool get canEdit => canEditSection(widget.api.user ?? {}, 'isp_card');
  final community = TextEditingController();
  final username = TextEditingController();
  final password = TextEditingController();
  bool busy = true, enabled = true, verifyTls = true, allowHttp = false;
  bool hasCommunity = false, hasPassword = false;
  bool tryPublicSnmp = true;
  int profiles = 0;
  String? error, message;

  @override
  void initState() {
    super.initState();
    load();
  }

  @override
  void dispose() {
    community.dispose();
    username.dispose();
    password.dispose();
    super.dispose();
  }

  void apply(Map<String, dynamic> data) {
    enabled = data['enabled'] != false;
    tryPublicSnmp = data['try_public_snmp'] != false;
    verifyTls = data['verify_tls'] != false;
    allowHttp = data['allow_http'] == true;
    hasCommunity = data['has_community'] == true;
    hasPassword = data['has_api_password'] == true;
    profiles = data['saved_snmp_profiles'] ?? 0;
    username.text = data['api_username'] ?? '';
  }

  Future<void> load() async {
    try {
      final data = await widget.api.request('/integrations/sas4/device-access');
      if (mounted) setState(() => apply(Map<String, dynamic>.from(data)));
    } catch (e) {
      if (mounted) setState(() => error = e.toString());
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> save() async {
    if (!canEdit) return;
    setState(() {
      busy = true;
      error = null;
      message = null;
    });
    try {
      final data = await widget.api.request(
        '/integrations/sas4/device-access',
        method: 'PUT',
        body: {
          'enabled': enabled,
          'try_public_snmp': tryPublicSnmp,
          'community': community.text.isEmpty ? null : community.text,
          'api_username': username.text.trim(),
          'api_password': password.text.isEmpty ? null : password.text,
          'verify_tls': verifyTls,
          'allow_http': allowHttp,
        },
      );
      if (mounted) {
        setState(() {
          apply(Map<String, dynamic>.from(data));
          community.clear();
          password.clear();
          message = 'Saved. Open Online users to detect devices automatically.';
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
    title: const AppText('Customer device access'),
    subtitle: const AppText('Automatic SNMP and device API detection'),
    children: [
      Padding(
        padding: const EdgeInsets.all(12),
        child: Column(
          children: [
            const AppText(
              'Read Ethernet speed and signal directly from online users’ IP addresses. Use device credentials, not your SAS4 login.',
            ),
            SwitchListTile(
              contentPadding: EdgeInsets.zero,
              title: const AppText('Automatic detection'),
              value: enabled,
              onChanged: busy || !canEdit
                  ? null
                  : (value) => setState(() => enabled = value),
            ),
            SwitchListTile(
              contentPadding: EdgeInsets.zero,
              title: const AppText('Check SNMP with public community'),
              subtitle: const AppText(
                'Tries v2c then v1. On MikroTik, enable SNMP read access for public; trap-community alone is not enough.',
              ),
              value: tryPublicSnmp,
              onChanged: busy || !canEdit
                  ? null
                  : (value) => setState(() => tryPublicSnmp = value),
            ),
            if (profiles > 0)
              Text(
                '$profiles saved SNMP credential(s) available for detection.',
              ),
            TextField(
              controller: community,
              obscureText: true,
              enabled: !busy && canEdit,
              autocorrect: false,
              enableSuggestions: false,
              decoration: InputDecoration(
                labelText: tr('Read-only SNMP community'),
                helperText: hasCommunity
                    ? 'Leave blank to keep the saved community.'
                    : 'Optional when saved SNMP profiles are available.',
              ),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: username,
              enabled: !busy && canEdit,
              autocorrect: false,
              enableSuggestions: false,
              decoration: InputDecoration(labelText: tr('Device API username')),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: password,
              obscureText: true,
              enabled: !busy && canEdit,
              autocorrect: false,
              enableSuggestions: false,
              decoration: InputDecoration(
                labelText: tr('Device API password'),
                helperText: hasPassword
                    ? 'Leave blank to keep the saved password.'
                    : 'For supported MikroTik REST and airOS devices.',
              ),
            ),
            SwitchListTile(
              contentPadding: EdgeInsets.zero,
              title: const AppText('Verify HTTPS certificates'),
              subtitle: const AppText(
                'Turn off only for devices with self-signed certificates.',
              ),
              value: verifyTls,
              onChanged: busy || !canEdit
                  ? null
                  : (value) => setState(() => verifyTls = value),
            ),
            SwitchListTile(
              contentPadding: EdgeInsets.zero,
              title: const AppText('Allow HTTP fallback'),
              subtitle: const AppText(
                'Sends device credentials without encryption. Use only on a trusted management network.',
              ),
              value: allowHttp,
              onChanged: busy || !canEdit
                  ? null
                  : (value) => setState(() => allowHttp = value),
            ),
            FilledButton(
              onPressed: busy || !canEdit ? null : save,
              child: const AppText('Save device access'),
            ),
            if (busy) const LinearProgressIndicator(),
            if (error != null)
              Text(
                error!,
                style: TextStyle(color: Theme.of(context).colorScheme.error),
              ),
            if (message != null) Text(message!),
          ],
        ),
      ),
    ],
  );
}
