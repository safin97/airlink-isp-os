import 'section_access.dart';
import 'dart:async';
import 'package:flutter/material.dart';
import 'api.dart';

class VpnSettings extends StatefulWidget {
  const VpnSettings({super.key, required this.api});
  final Api api;
  @override
  State<VpnSettings> createState() => _VpnSettingsState();
}

class _VpnSettingsState extends State<VpnSettings> {
  final server = TextEditingController();
  final username = TextEditingController();
  final password = TextEditingController();
  final psk = TextEditingController();
  final routes = TextEditingController();
  Map<String, dynamic>? data;
  String? error;
  bool busy = false, reading = false, dirty = false;
  int generation = 0;
  Timer? timer;
  bool get owner => hasSection(widget.api.user ?? {}, 'vpn');

  @override
  void initState() {
    super.initState();
    if (owner) load();
  }

  @override
  void dispose() {
    timer?.cancel();
    for (final controller in [server, username, password, psk, routes]) {
      controller.dispose();
    }
    super.dispose();
  }

  void schedule() {
    timer?.cancel();
    if (mounted && owner && data?['supported'] != false) {
      timer = Timer(const Duration(seconds: 5), load);
    }
  }

  void fill(Map<String, dynamic> value) {
    server.text = value['server'] ?? '';
    username.text = value['username'] ?? '';
    routes.text = (value['routes'] as List? ?? []).join('\n');
  }

  Future<void> load() async {
    if (!owner || reading || busy) return;
    reading = true;
    final started = generation;
    try {
      final value = Map<String, dynamic>.from(await widget.api.request('/vpn'));
      if (!mounted || started != generation) return;
      setState(() {
        if (data == null && !dirty) fill(value);
        data = value;
        error = null;
      });
    } catch (e) {
      if (mounted && started == generation) {
        setState(() => error = e.toString());
      }
    } finally {
      reading = false;
      schedule();
    }
  }

  Future<void> act(String action) async {
    if (!owner || busy) return;
    generation++;
    timer?.cancel();
    setState(() {
      busy = true;
      error = null;
    });
    try {
      final body = action == 'save'
          ? {
              'server': server.text.trim(),
              'username': username.text.trim(),
              'password': password.text,
              'psk': psk.text,
              'routes': routes.text
                  .split(RegExp(r'[\s,]+'))
                  .where((s) => s.isNotEmpty)
                  .toList(),
            }
          : <String, dynamic>{};
      final value = Map<String, dynamic>.from(
        await widget.api.request(
          '/vpn/$action',
          method: 'POST',
          body: body,
          retry: false,
        ),
      );
      if (!mounted) return;
      setState(() {
        data = value;
        if (action == 'save' || action == 'delete') {
          fill(value);
          password.clear();
          psk.clear();
          dirty = false;
        }
      });
    } catch (e) {
      if (mounted) setState(() => error = e.toString());
    } finally {
      if (mounted) setState(() => busy = false);
      schedule();
    }
  }

  Future<void> remove() async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Remove saved VPN?'),
        content: const Text(
          'Remove the saved server, username, password and shared key from this AirLink PC.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('Remove'),
          ),
        ],
      ),
    );
    if (confirmed == true && mounted) await act('delete');
  }

  @override
  Widget build(BuildContext context) {
    if (!owner) return const SizedBox.shrink();
    final supported = data?['supported'] == true;
    final configured = data?['configured'] == true;
    final status = data?['status'];
    final active = status == 'connected' || status == 'connecting';
    final editable =
        canEditSection(widget.api.user ?? {}, 'vpn') &&
        supported &&
        !busy &&
        !active;
    final label = switch (status) {
      'connected' => 'Connected',
      'connecting' => 'Connecting…',
      'disconnected' => 'Disconnected',
      'failed' => 'Connection failed',
      'not_configured' => 'Not configured',
      'unavailable' => 'Unavailable',
      _ => 'Checking VPN status…',
    };
    Widget field(
      TextEditingController controller,
      String label, {
      bool secret = false,
      String? helper,
      int lines = 1,
    }) => Padding(
      padding: const EdgeInsets.only(top: 16),
      child: TextField(
        controller: controller,
        enabled: editable,
        obscureText: secret,
        autocorrect: false,
        enableSuggestions: false,
        maxLines: lines,
        onChanged: (_) => setState(() => dirty = true),
        decoration: InputDecoration(
          labelText: label,
          helperText: helper,
          helperMaxLines: 3,
          border: const OutlineInputBorder(),
        ),
      ),
    );
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text(
              'L2TP/IPsec VPN',
              style: TextStyle(fontSize: 20, fontWeight: FontWeight.w600),
            ),
            const SizedBox(height: 8),
            const Text(
              'Connect this AirLink server to your VPN server. Access is controlled by your Access Role.',
            ),
            const SizedBox(height: 12),
            Text('VPN status: $label', key: const ValueKey('vpn-status')),
            if (data?['addresses'] is List &&
                (data!['addresses'] as List).isNotEmpty)
              Text('VPN address: ${(data!['addresses'] as List).join(', ')}'),
            if (data?['reason'] != null) Text(data!['reason']),
            if (busy || (data == null && error == null))
              const LinearProgressIndicator(),
            if (error != null)
              Text(
                error!,
                style: TextStyle(color: Theme.of(context).colorScheme.error),
              ),
            if (status == 'failed')
              const Text(
                'Check the VPN server, username, password and IPsec shared key, then reconnect.',
              ),
            field(
              server,
              'VPN server address',
              helper:
                  'Public IP address or hostname, without https:// or a port.',
            ),
            field(username, 'VPN username'),
            field(
              password,
              'VPN password',
              secret: true,
              helper: data?['has_password'] == true
                  ? 'Saved. Leave blank to keep the current password.'
                  : 'Enter the password for your VPN account.',
            ),
            field(
              psk,
              'IPsec shared key',
              secret: true,
              helper: data?['has_psk'] == true
                  ? 'Saved. Leave blank to keep the current shared key.'
                  : 'Enter the pre-shared key from your VPN server.',
            ),
            field(
              routes,
              'Remote subnets (optional)',
              lines: 3,
              helper:
                  'One per line, for example 192.168.88.0/24. Only these subnets use the VPN; normal internet traffic keeps its existing route.',
            ),
            const SizedBox(height: 12),
            const Text(
              'Save, then connect. Disconnect before editing. Connections are started manually and do not automatically reconnect after a restart.',
            ),
            const SizedBox(height: 16),
            Wrap(
              spacing: 12,
              runSpacing: 8,
              children: [
                FilledButton(
                  onPressed: editable ? () => act('save') : null,
                  child: const Text('Save VPN'),
                ),
                OutlinedButton(
                  onPressed:
                      supported && configured && !busy && !active && !dirty
                      ? () => act('connect')
                      : null,
                  child: const Text('Connect'),
                ),
                OutlinedButton(
                  onPressed:
                      canEditSection(widget.api.user ?? {}, 'vpn') &&
                          supported &&
                          !busy &&
                          active
                      ? () => act('disconnect')
                      : null,
                  child: const Text('Disconnect'),
                ),
                TextButton(
                  onPressed:
                      canDeleteSection(widget.api.user ?? {}, 'vpn') &&
                          !busy &&
                          configured
                      ? remove
                      : null,
                  child: const Text('Remove VPN'),
                ),
                if (error != null)
                  TextButton(
                    onPressed: busy ? null : load,
                    child: const Text('Retry status'),
                  ),
              ],
            ),
            if (dirty) const Text('Save your changes before connecting.'),
          ],
        ),
      ),
    );
  }
}
