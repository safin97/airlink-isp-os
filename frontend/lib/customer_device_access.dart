import 'package:flutter/material.dart';

import 'api.dart';
import 'section_access.dart';
import 'app_language.dart';

class CustomerDeviceAccess extends StatefulWidget {
  const CustomerDeviceAccess({
    super.key,
    required this.api,
    this.embedded = false,
  });
  final Api api;
  final bool embedded;
  @override
  State<CustomerDeviceAccess> createState() => _CustomerDeviceAccessState();
}

class _CustomerDeviceAccessState extends State<CustomerDeviceAccess>
    with LanguageRebuild {
  bool get canEdit => canEditSection(widget.api.user ?? {}, 'isp_card');
  final community = TextEditingController();
  bool busy = true, enabled = true;
  bool hasCommunity = false;
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
    super.dispose();
  }

  void apply(Map<String, dynamic> data) {
    enabled = data['enabled'] != false;
    tryPublicSnmp = data['try_public_snmp'] != false;
    hasCommunity = data['has_community'] == true;
    profiles = data['saved_snmp_profiles'] ?? 0;
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
        },
      );
      if (mounted) {
        setState(() {
          apply(Map<String, dynamic>.from(data));
          community.clear();
          message =
              'Saved. SNMP collection runs automatically in the background.';
        });
      }
    } catch (e) {
      if (mounted) setState(() => error = e.toString());
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => widget.embedded
      ? settingsContent()
      : ExpansionTile(
          title: const AppText('Customer device access'),
          subtitle: const AppText('Automatic SNMP detection'),
          children: [
            Padding(
              padding: const EdgeInsets.all(12),
              child: settingsContent(),
            ),
          ],
        );

  Widget settingsContent() => Column(
    crossAxisAlignment: CrossAxisAlignment.stretch,
    children: [
      const AppText(
        'Read ether1 speed, wireless signal and SSID from online users’ IP addresses using SNMP.',
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
          'Tries SNMP v1, then v2, then saved v3 credentials. On MikroTik, enable SNMP read access for public; trap-community alone is not enough.',
        ),
        value: tryPublicSnmp,
        onChanged: busy || !canEdit
            ? null
            : (value) => setState(() => tryPublicSnmp = value),
      ),
      if (profiles > 0)
        Text('$profiles saved SNMP credential(s) available for detection.'),
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
  );
}
