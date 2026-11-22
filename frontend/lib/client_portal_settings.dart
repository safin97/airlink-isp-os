import 'package:flutter/material.dart';
import 'package:url_launcher/link.dart';
import 'api.dart';
import 'app_language.dart';

class ClientPortalSettings extends StatefulWidget {
  final Api api;
  const ClientPortalSettings({super.key, required this.api});
  @override
  State<ClientPortalSettings> createState() => _ClientPortalSettingsState();
}

class _ClientPortalSettingsState extends State<ClientPortalSettings> {
  final networks = TextEditingController();
  bool enabled = false, busy = true;
  String? message;
  @override
  void initState() {
    super.initState();
    load();
  }

  @override
  void dispose() {
    networks.dispose();
    super.dispose();
  }

  Future<void> load() async {
    try {
      final data = await widget.api.request('/client-portal');
      if (mounted) {
        setState(() {
          enabled = data['enabled'];
          networks.text = (data['subscriber_networks'] as List).join('\n');
        });
      }
    } catch (e) {
      if (mounted) setState(() => message = e.toString());
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> save() async {
    setState(() {
      busy = true;
      message = null;
    });
    try {
      await widget.api.request(
        '/client-portal',
        method: 'PUT',
        body: {
          'enabled': enabled,
          'subscriber_networks': networks.text
              .split(RegExp(r'[\s,]+'))
              .where((s) => s.isNotEmpty)
              .toList(),
        },
      );
      if (mounted) {
        setState(
          () => message =
              'Client portal saved. Existing client sessions have been signed out.',
        );
      }
    } catch (e) {
      if (mounted) setState(() => message = e.toString());
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    children: [
      const AppText(
        'Customers sign in with their SAS4 PPPoE account and recharge only their own service. Your saved SAS4 connection and FIB merchant settings are used.',
      ),
      SwitchListTile(
        contentPadding: EdgeInsets.zero,
        title: const AppText('Enable client recharge portal'),
        value: enabled,
        onChanged: busy ? null : (value) => setState(() => enabled = value),
      ),
      TextField(
        controller: networks,
        enabled: !busy,
        minLines: 2,
        maxLines: 4,
        decoration: InputDecoration(
          labelText: tr('PPPoE subscriber networks for automatic login'),
          hintText: '10.0.0.0/8',
          border: const OutlineInputBorder(),
        ),
      ),
      const SizedBox(height: 12),
      const AppText(
        'Use subscriber IP ranges visible before shared NAT. Automatic login requires a unique RADIUS session updated within two minutes. Other connections use password login. Leave the list empty to disable network auto-login.',
      ),
      const SizedBox(height: 16),
      FilledButton(
        onPressed: busy ? null : save,
        child: const AppText('Save client portal'),
      ),
      Link(
        uri: Uri.base.resolve('/client'),
        target: LinkTarget.blank,
        builder: (_, follow) => TextButton(
          onPressed: follow,
          child: const AppText('Open client portal'),
        ),
      ),
      if (message != null) Text(message!),
    ],
  );
}
