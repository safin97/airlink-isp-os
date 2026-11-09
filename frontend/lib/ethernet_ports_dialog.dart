import 'dart:async';
import 'package:flutter/material.dart';
import 'api.dart';

class EthernetPortsDialog extends StatefulWidget {
  const EthernetPortsDialog({
    super.key,
    required this.api,
    required this.device,
  });
  final Api api;
  final Map<String, dynamic> device;

  @override
  State<EthernetPortsDialog> createState() => _EthernetPortsDialogState();
}

class _EthernetPortsDialogState extends State<EthernetPortsDialog> {
  Map<String, dynamic>? data;
  String? error;
  bool busy = false;
  Timer? timer;

  @override
  void initState() {
    super.initState();
    load();
    timer = Timer.periodic(const Duration(seconds: 15), (_) => load());
  }

  @override
  void dispose() {
    timer?.cancel();
    super.dispose();
  }

  Future<void> load() async {
    if (busy) return;
    setState(() => busy = true);
    try {
      final result = await widget.api.request(
        '/devices/${Uri.encodeComponent(widget.device['id'].toString())}/ethernet-ports',
      );
      if (mounted) {
        setState(() {
          data = Map<String, dynamic>.from(result);
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
      if (mounted) setState(() => busy = false);
    }
  }

  String rate(dynamic value) => value is num
      ? '${(value / 1000000).toStringAsFixed(3)} Mbps'
      : 'Unavailable';

  @override
  Widget build(BuildContext context) {
    final ports = (data?['ports'] as List?) ?? [];
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
              Text('${widget.device['ip_address'] ?? ''} · MikroTik · SNMPv2c'),
              if (busy) const LinearProgressIndicator(),
              if (error != null)
                Text(
                  error!,
                  style: TextStyle(color: Theme.of(context).colorScheme.error),
                ),
              if (data != null && data!['supported'] != true)
                const Text(
                  'Select MikroTik switch and an SNMPv2c profile in Edit device. Enable SNMP on the switch with the matching community.',
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
                  'Traffic is averaged between monitoring polls (${data!['poll_interval']} seconds), from the switch’s perspective. Two valid samples are required. This view refreshes every 15 seconds.',
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
          onPressed: () => Navigator.pop(context),
          child: const Text('Close'),
        ),
      ],
    );
  }
}
