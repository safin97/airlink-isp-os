import 'dart:convert';
import 'package:flutter/material.dart';
import 'api.dart';
import 'app_language.dart';
import 'wireless_clients_dialog.dart';

class DeviceManagementDialog extends StatefulWidget {
  const DeviceManagementDialog({
    super.key,
    required this.api,
    required this.device,
    required this.canEdit,
  });
  final Api api;
  final Map<String, dynamic> device;
  final bool canEdit;
  @override
  State<DeviceManagementDialog> createState() => _DeviceManagementDialogState();
}

class _DeviceManagementDialogState extends State<DeviceManagementDialog> {
  final controls = <String, TextEditingController>{};
  List<Map<String, dynamic>> radios = [];
  bool busy = false;
  String? message, error;
  String keyOf(Map radio) => '${radio['menu']}:${radio['id']}';
  String get path =>
      '/devices/${Uri.encodeComponent(widget.device['id'].toString())}/wireless-settings';

  @override
  void initState() {
    super.initState();
    load();
  }

  @override
  void dispose() {
    for (final c in controls.values) {
      c.dispose();
    }
    super.dispose();
  }

  Future<void> load() async {
    setState(() {
      busy = true;
      error = null;
      message = null;
    });
    try {
      final result = await widget.api.request(path);
      if (!mounted) return;
      final next = (result['radios'] as List)
          .map((r) => Map<String, dynamic>.from(r))
          .toList();
      for (final radio in next) {
        final key = keyOf(radio);
        controls.putIfAbsent(key, () => TextEditingController()).text =
            radio['ssid'] ?? '';
      }
      setState(() {
        radios = next;
        message = result['message'];
      });
    } catch (e) {
      if (mounted) setState(() => error = e.toString());
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> apply(Map<String, dynamic> radio) async {
    final ssid = controls[keyOf(radio)]!.text;
    if (ssid.isEmpty ||
        utf8.encode(ssid).length > 32 ||
        ssid.runes.any((c) => c < 32 || c == 127)) {
      setState(
        () =>
            error = 'SSID must be 1–32 UTF-8 bytes without control characters.',
      );
      return;
    }
    setState(() {
      busy = true;
      error = null;
      message = null;
    });
    try {
      final result = await widget.api.request(
        path,
        method: 'PUT',
        body: {
          'menu': radio['menu'],
          'radio_id': radio['id'],
          'previous_ssid': radio['ssid'],
          'ssid': ssid,
        },
      );
      if (mounted) {
        setState(() {
          radio['ssid'] = ssid;
          message = result['status'] == 'unchanged'
              ? 'SSID is unchanged.'
              : 'Device accepted the SSID change. Reload settings to verify it after clients reconnect.';
        });
      }
    } catch (e) {
      if (mounted) setState(() => error = e.toString());
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => PopScope(
    canPop: !busy,
    child: AlertDialog(
      title: Text('${tr('Manage device')} — ${widget.device['name']}'),
      content: SizedBox(
        width: 620,
        child: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(widget.device['ip_address'] ?? ''),
              const SizedBox(height: 12),
              FilledButton.tonalIcon(
                onPressed: busy
                    ? null
                    : () => showDialog<void>(
                        context: context,
                        builder: (_) => WirelessClientsDialog(
                          api: widget.api,
                          device: widget.device,
                        ),
                      ),
                icon: const Icon(Icons.people_outline),
                label: const AppText('Registration clients'),
              ),
              const SizedBox(height: 16),
              const AppText(
                'Wireless SSID',
                style: TextStyle(fontWeight: FontWeight.bold),
              ),
              if (!widget.canEdit)
                const AppText(
                  'Read-only access. Ask the owner for Towers edit permission.',
                ),
              if (busy) const LinearProgressIndicator(),
              if (message != null)
                Padding(
                  padding: const EdgeInsets.symmetric(vertical: 12),
                  child: Text(message!),
                ),
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
              if (radios.isEmpty &&
                  (widget.device['telemetry']?['wireless_ssids'] as List? ?? [])
                      .isNotEmpty)
                Text(
                  'Last reported SSID: ${(widget.device['telemetry']['wireless_ssids'] as List).join(', ')}',
                ),
              for (final radio in radios)
                Padding(
                  padding: const EdgeInsets.only(top: 14),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text('${radio['name']} · ${radio['menu']}'),
                      Text(
                        'Current SSID: ${radio['ssid'] ?? 'Inherited / unavailable'}',
                      ),
                      TextField(
                        key: ValueKey('ssid-${keyOf(radio)}'),
                        controller: controls[keyOf(radio)],
                        enabled:
                            !busy &&
                            widget.canEdit &&
                            radio['editable'] == true,
                        decoration: const InputDecoration(
                          labelText: 'New SSID',
                        ),
                        onChanged: (_) => setState(() {}),
                      ),
                      if (radio['reason'] != null) Text(radio['reason']),
                      if (widget.canEdit && radio['editable'] == true) ...[
                        const AppText(
                          'Changing SSID disconnects wireless clients. Update their connection settings to reconnect.',
                        ),
                        TextButton(
                          onPressed:
                              busy ||
                                  controls[keyOf(radio)]!.text == radio['ssid']
                              ? null
                              : () => apply(radio),
                          child: const AppText('Apply SSID'),
                        ),
                      ],
                    ],
                  ),
                ),
            ],
          ),
        ),
      ),
      actions: [
        TextButton(
          onPressed: busy ? null : load,
          child: const AppText('Reload settings'),
        ),
        TextButton(
          onPressed: busy ? null : () => Navigator.pop(context),
          child: const AppText('Close'),
        ),
      ],
    ),
  );
}
