import 'package:flutter/material.dart';
import 'api.dart';
import 'section_access.dart';
import 'app_language.dart';

class CustomerDeviceAccess extends StatefulWidget {
  const CustomerDeviceAccess({super.key, required this.api, this.onSaved});
  final Api api;
  final VoidCallback? onSaved;
  @override
  State<CustomerDeviceAccess> createState() => _CustomerDeviceAccessState();
}

class _CustomerDeviceAccessState extends State<CustomerDeviceAccess>
    with LanguageRebuild {
  final username = TextEditingController();
  final password = TextEditingController();
  final community = TextEditingController();
  bool busy = true,
      enabled = true,
      verifyTls = true,
      allowHttp = true,
      hasPassword = false,
      hasCommunity = false,
      tryPublicSnmp = false;
  String? error, message;
  bool get canEdit => canEditSection(widget.api.user ?? {}, 'isp_card');

  @override
  void initState() {
    super.initState();
    load();
  }

  @override
  void dispose() {
    username.dispose();
    password.dispose();
    community.dispose();
    super.dispose();
  }

  void apply(Map<String, dynamic> data) {
    username.text = data['api_username'] ?? '';
    enabled = data['enabled'] != false;
    verifyTls = data['verify_tls'] != false;
    allowHttp = data['allow_http'] != false;
    hasPassword = data['has_api_password'] == true;
    hasCommunity = data['has_community'] == true;
    tryPublicSnmp = data['try_public_snmp'] == true;
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
    final hasApiLogin =
        username.text.trim().isNotEmpty &&
        (hasPassword || password.text.isNotEmpty);
    final hasSnmp =
        hasCommunity || community.text.trim().isNotEmpty || tryPublicSnmp;
    if (enabled && !hasApiLogin && !hasSnmp) {
      setState(
        () => error =
            'Enter a device login, an SNMP community, or enable public SNMP detection.',
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
        '/integrations/sas4/device-access',
        method: 'PUT',
        body: {
          'enabled': enabled,
          'api_username': username.text.trim(),
          'api_password': password.text.isEmpty ? null : password.text,
          'community': community.text.trim().isEmpty
              ? null
              : community.text.trim(),
          'verify_tls': verifyTls,
          'allow_http': allowHttp,
          'try_public_snmp': tryPublicSnmp,
        },
      );
      if (mounted) {
        setState(() {
          apply(Map<String, dynamic>.from(data));
          password.clear();
          community.clear();
          message =
              'Saved. Online users will auto-detect with SNMP v1/v2 and device login fallback.';
        });
        widget.onSaved?.call();
      }
    } catch (e) {
      if (mounted) setState(() => error = e.toString());
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => Card(
    child: ExpansionTile(
      title: const AppText('Default device login'),
      subtitle: const AppText('Used for automatic online user readings'),
      children: [
        Padding(
          padding: const EdgeInsets.all(12),
          child: Column(
            children: [
              const AppText(
                'Automatically detect MikroTik and Ubiquiti devices and read Ethernet speed, wireless signal and SSID. SNMP v2c and v1 are tried first, followed by the saved device login.',
              ),
              SwitchListTile(
                contentPadding: EdgeInsets.zero,
                title: const AppText('Automatic device readings'),
                value: enabled,
                onChanged: busy || !canEdit
                    ? null
                    : (v) => setState(() => enabled = v),
              ),
              TextField(
                key: const ValueKey('online-device-username'),
                controller: username,
                enabled: !busy && canEdit,
                decoration: const InputDecoration(labelText: 'Device username'),
              ),
              TextField(
                key: const ValueKey('online-device-community'),
                controller: community,
                enabled: !busy && canEdit,
                obscureText: true,
                enableSuggestions: false,
                autocorrect: false,
                decoration: InputDecoration(
                  labelText: 'Read-only SNMP community',
                  helperText: hasCommunity
                      ? 'Leave blank to keep the saved community. It is tried with SNMP v2c and v1.'
                      : 'Used for automatic SNMP v2c and v1 detection.',
                ),
              ),
              CheckboxListTile(
                contentPadding: EdgeInsets.zero,
                title: const AppText('Also try public SNMP community'),
                subtitle: const AppText('Tries SNMP v2c and v1.'),
                value: tryPublicSnmp,
                onChanged: busy || !canEdit
                    ? null
                    : (v) => setState(() => tryPublicSnmp = v!),
              ),
              TextField(
                key: const ValueKey('online-device-password'),
                controller: password,
                enabled: !busy && canEdit,
                obscureText: true,
                enableSuggestions: false,
                autocorrect: false,
                decoration: InputDecoration(
                  labelText: 'Device password',
                  helperText: hasPassword
                      ? 'Leave blank to keep the saved password.'
                      : null,
                ),
              ),
              CheckboxListTile(
                contentPadding: EdgeInsets.zero,
                title: const AppText('Allow HTTP connections'),
                value: allowHttp,
                onChanged: busy || !canEdit
                    ? null
                    : (v) => setState(() => allowHttp = v!),
              ),
              CheckboxListTile(
                contentPadding: EdgeInsets.zero,
                title: const AppText('Verify device TLS certificate'),
                value: verifyTls,
                onChanged: busy || !canEdit
                    ? null
                    : (v) => setState(() => verifyTls = v!),
              ),
              FilledButton(
                onPressed: busy || !canEdit ? null : save,
                child: const AppText('Save device login'),
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
    ),
  );
}
