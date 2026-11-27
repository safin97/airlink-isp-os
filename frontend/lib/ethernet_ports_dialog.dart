import 'dart:async';
import 'dart:convert';
import 'package:flutter/material.dart';
import 'api.dart';

class EthernetPortsDialog extends StatefulWidget {
  const EthernetPortsDialog({
    super.key,
    required this.api,
    required this.device,
    this.onChanged,
  });
  final Api api;
  final Map<String, dynamic> device;
  final Future<void> Function()? onChanged;

  @override
  State<EthernetPortsDialog> createState() => _EthernetPortsDialogState();
}

class _EthernetPortsDialogState extends State<EthernetPortsDialog> {
  Map<String, dynamic>? data;
  String? error;
  bool busy = false;
  bool fetching = false;
  bool saving = false;
  bool dirty = false;
  String? selectedPort;
  String? saveError;
  bool saved = false;
  int selectionRevision = 0;
  Timer? timer;

  @override
  void initState() {
    super.initState();
    load();
    timer = Timer.periodic(
      const Duration(seconds: 5),
      (_) => load(quiet: true),
    );
  }

  @override
  void dispose() {
    timer?.cancel();
    super.dispose();
  }

  Future<void> load({bool quiet = false}) async {
    if (fetching || saving) return;
    fetching = true;
    final revision = selectionRevision;
    if (!quiet) setState(() => busy = true);
    try {
      final result = await widget.api.request(
        '/devices/${Uri.encodeComponent(widget.device['id'].toString())}/ethernet-ports',
      );
      if (mounted &&
          revision == selectionRevision &&
          (error != null || jsonEncode(data) != jsonEncode(result))) {
        setState(() {
          data = Map<String, dynamic>.from(result);
          if (!dirty) selectedPort = data!['speed_port'] as String?;
          error = null;
        });
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          error = e.toString();
          data = null;
        });
      }
    } finally {
      fetching = false;
      if (mounted && busy) setState(() => busy = false);
    }
  }

  String rate(dynamic value) => value is num
      ? '${(value / 1000000).toStringAsFixed(3)} Mbps'
      : 'Unavailable';

  Future<void> savePort() async {
    selectionRevision++;
    setState(() {
      saving = true;
      saveError = null;
      saved = false;
    });
    try {
      await widget.api.request(
        '/devices/${Uri.encodeComponent(widget.device['id'].toString())}/ethernet-display',
        method: 'PUT',
        body: {'port': selectedPort},
      );
      if (!mounted) return;
      setState(() {
        dirty = false;
        saved = true;
      });
      await widget.onChanged?.call();
    } catch (e) {
      if (mounted) setState(() => saveError = e.toString());
    } finally {
      if (mounted) setState(() => saving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final ports = (data?['ports'] as List?) ?? [];
    final choices = <String>{
      ...((data?['speed_port_choices'] as List?) ?? []).whereType<String>(),
      if (selectedPort != null) selectedPort!,
    }.toList()..sort();
    const labels = {
      'connected': 'Running',
      'disconnected': 'Not running · Link down',
      'disabled': 'Not running · Disabled',
      'testing': 'Not running · Testing',
      'dormant': 'Not running · Dormant',
      'not_present': 'Not running · Not present',
      'lower_layer_down': 'Not running · Lower layer down',
      'unknown': 'Unknown',
    };
    final running = ports.where((p) => p['state'] == 'connected').length;
    final notRunning = ports
        .where(
          (p) =>
              labels.containsKey(p['state']) &&
              p['state'] != 'connected' &&
              p['state'] != 'unknown',
        )
        .length;
    final unknown = ports.length - running - notRunning;
    return AlertDialog(
      title: Text('Ethernet ports — ${widget.device['name']}'),
      content: SizedBox(
        width: 800,
        child: SingleChildScrollView(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(
                [
                  widget.device['ip_address'] ?? '',
                  widget.device['vendor_label'] ??
                      widget.device['vendor'] ??
                      '',
                  if (data?['snmp_version'] != null)
                    'SNMPv${data!['snmp_version']}',
                ].where((value) => value.toString().isNotEmpty).join(' · '),
              ),
              if (busy) const LinearProgressIndicator(),
              if (error != null)
                Text(
                  error!,
                  style: TextStyle(color: Theme.of(context).colorScheme.error),
                ),
              if (data?['can_select_speed_port'] == true) ...[
                const SizedBox(height: 12),
                const Text('Port shown in the Ethernet speed column'),
                DropdownButton<String>(
                  key: const ValueKey('ethernet-speed-port'),
                  isExpanded: true,
                  value: selectedPort ?? '',
                  items: [
                    const DropdownMenuItem(
                      value: '',
                      child: Text('Automatic (available port)'),
                    ),
                    ...choices.map(
                      (name) =>
                          DropdownMenuItem(value: name, child: Text(name)),
                    ),
                  ],
                  onChanged: saving
                      ? null
                      : (value) => setState(() {
                          selectedPort = value == '' ? null : value;
                          dirty = true;
                          saved = false;
                        }),
                ),
                const Text(
                  'Saved for this device and shared with everyone who can view it. Last reported speed stays visible during an outage.',
                ),
                FilledButton(
                  onPressed: saving || !dirty ? null : savePort,
                  child: Text(saving ? 'Saving…' : 'Save displayed port'),
                ),
                if (saved) const Text('Displayed port saved.'),
                if (saveError != null)
                  Text(
                    saveError!,
                    style: TextStyle(
                      color: Theme.of(context).colorScheme.error,
                    ),
                  ),
                const SizedBox(height: 12),
              ],
              if (data != null && data!['supported'] != true)
                const Text(
                  'Assign an SNMP profile in Edit device and enable matching SNMP access on the device to see all reported Ethernet ports.',
                ),
              if (data?['supported'] == true) ...[
                Text('SNMP: ${data!['snmp_status']}'),
                Text(
                  '${ports.length} ports · $running running · $notRunning not running · $unknown unknown',
                ),
                const Text(
                  'All reported Ethernet and SFP ports, including disconnected and disabled ports.',
                ),
                const SizedBox(height: 8),
                if (ports.isEmpty)
                  const Text(
                    'No Ethernet ports reported yet. Check SNMP access and wait for the next poll.',
                  ),
                if (ports.isNotEmpty)
                  SingleChildScrollView(
                    scrollDirection: Axis.horizontal,
                    child: DataTable(
                      columns: const [
                        DataColumn(label: Text('Port')),
                        DataColumn(label: Text('Status')),
                        DataColumn(label: Text('Link speed')),
                        DataColumn(label: Text('Receive traffic (RX)')),
                        DataColumn(label: Text('Transmit traffic (TX)')),
                      ],
                      rows: ports
                          .map(
                            (p) => DataRow(
                              cells: [
                                DataCell(Text(p['name'].toString())),
                                DataCell(
                                  Row(
                                    mainAxisSize: MainAxisSize.min,
                                    children: [
                                      Icon(
                                        Icons.circle,
                                        size: 10,
                                        color: switch (p['state']) {
                                          'connected' => Colors.green,
                                          'disconnected' => Colors.orange,
                                          'disabled' => Colors.red,
                                          _ => Colors.grey,
                                        },
                                      ),
                                      const SizedBox(width: 6),
                                      Text(labels[p['state']] ?? 'Unknown'),
                                    ],
                                  ),
                                ),
                                DataCell(
                                  Text(
                                    p['speed_mbps'] == null
                                        ? '—'
                                        : '${p['speed_mbps']} Mbps',
                                  ),
                                ),
                                DataCell(Text(rate(p['rx_bps']))),
                                DataCell(Text(rate(p['tx_bps']))),
                              ],
                            ),
                          )
                          .toList(),
                    ),
                  ),
                const SizedBox(height: 12),
                Text(
                  'Traffic is averaged between monitoring polls (${data!['poll_interval']} seconds), from the device’s perspective. Two valid samples are required. This view refreshes every 5 seconds.',
                ),
                if (data!['collected_at'] != null)
                  Text('Last sample: ${data!['collected_at']}'),
              ],
            ],
          ),
        ),
      ),
      actions: [
        TextButton(onPressed: busy ? null : load, child: const Text('Refresh')),
        TextButton(
          onPressed: saving ? null : () => Navigator.pop(context),
          child: const Text('Close'),
        ),
      ],
    );
  }
}
