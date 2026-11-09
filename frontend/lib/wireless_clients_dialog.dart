import 'dart:async';
import 'dart:convert';
import 'package:flutter/material.dart';
import 'api.dart';
import 'app_language.dart';

class WirelessClientsDialog extends StatefulWidget {
  const WirelessClientsDialog({
    super.key,
    required this.api,
    required this.device,
  });
  final Api api;
  final Map<String, dynamic> device;
  @override
  State<WirelessClientsDialog> createState() => _WirelessClientsDialogState();
}

class _WirelessClientsDialogState extends State<WirelessClientsDialog> {
  Map<String, dynamic>? data;
  String? error;
  bool fetching = false;
  Timer? timer;

  @override
  void initState() {
    super.initState();
    load();
    timer = Timer.periodic(const Duration(seconds: 5), (_) => load());
  }

  @override
  void dispose() {
    timer?.cancel();
    super.dispose();
  }

  Future<void> load() async {
    if (fetching) return;
    fetching = true;
    try {
      final next = Map<String, dynamic>.from(
        await widget.api.request(
          '/devices/${Uri.encodeComponent(widget.device['id'].toString())}/wireless-clients',
        ),
      );
      if (mounted && (error != null || jsonEncode(data) != jsonEncode(next))) {
        setState(() {
          data = next;
          error = null;
        });
      }
    } catch (e) {
      if (mounted) setState(() => error = e.toString());
    } finally {
      fetching = false;
    }
  }

  @override
  Widget build(BuildContext context) {
    final rows = (data?['clients'] as List?) ?? [];
    return AlertDialog(
      title: Text(
        '${tr('Connected wireless clients')} — ${widget.device['name']}',
      ),
      content: SizedBox(
        width: 760,
        height: 360,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            if (error != null) ...[
              Text(
                error!,
                style: TextStyle(color: Theme.of(context).colorScheme.error),
              ),
              TextButton(onPressed: load, child: const AppText('Retry')),
            ],
            if (data == null && error == null) const LinearProgressIndicator(),
            if (data != null) ...[
              Text('${data!['total'] ?? '—'} ${tr('registered clients')}'),
              if (data!['collected_at'] != null)
                Text('${tr('Collected')}: ${data!['collected_at']}'),
              const SizedBox(height: 12),
              if (rows.isNotEmpty)
                const AppText(
                  'PPPoE usernames require a unique MAC match in active sessions. Unmatched clients show Unavailable.',
                ),
              if (rows.isNotEmpty &&
                  data!['username_lookup_status'] == 'not_configured')
                const AppText(
                  'For SAS4 matching, configure your SAS4 connection and enable ISP Card access.',
                ),
              if (rows.isEmpty)
                AppText(
                  data!['status'] == 'available'
                      ? 'No connected wireless clients.'
                      : data!['status'] == 'stale'
                      ? 'Registration data is out of date. Waiting for a new device poll.'
                      : 'The device has not supplied its wireless registration list yet.',
                ),
              if (rows.isNotEmpty) ...[
                if (data!['total'] is num &&
                    (data!['total'] as num) > rows.length)
                  Text(
                    '${tr('Showing')} ${rows.length} ${tr('of')} ${data!['total']}',
                  ),
                Expanded(
                  child: SingleChildScrollView(
                    child: SingleChildScrollView(
                      scrollDirection: Axis.horizontal,
                      child: DataTable(
                        columns: [
                          for (final label in [
                            'MAC address',
                            'PPPoE username',
                            'SSID',
                            'Signal',
                          ])
                            DataColumn(label: AppText(label)),
                        ],
                        rows: rows
                            .map(
                              (row) => DataRow(
                                cells: [
                                  DataCell(
                                    SelectableText(row['mac_address'] ?? '—'),
                                  ),
                                  DataCell(
                                    Text(
                                      row['pppoe_username'] ??
                                          (row['pppoe_username_status'] ==
                                                  'pending'
                                              ? 'Checking…'
                                              : 'Unavailable'),
                                    ),
                                  ),
                                  DataCell(
                                    Text(
                                      row['ssid'] == ''
                                          ? '—'
                                          : row['ssid'] ?? '—',
                                    ),
                                  ),
                                  DataCell(
                                    Text(
                                      row['signal_dbm'] == null
                                          ? '—'
                                          : '${row['signal_dbm']} dBm',
                                    ),
                                  ),
                                ],
                              ),
                            )
                            .toList(),
                      ),
                    ),
                  ),
                ),
              ],
            ],
          ],
        ),
      ),
      actions: [
        TextButton(
          onPressed: () => Navigator.pop(context),
          child: const AppText('Close'),
        ),
      ],
    );
  }
}
