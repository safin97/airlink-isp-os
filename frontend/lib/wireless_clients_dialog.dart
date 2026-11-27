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
    final rows = ((data?['clients'] as List?) ?? [])
        .map(
          (row) => error == null ? row : {...row as Map, 'status': 'unknown'},
        )
        .toList();
    String localTime(dynamic value) {
      final time = DateTime.tryParse(value?.toString() ?? '')?.toLocal();
      if (time == null) return '—';
      String two(int n) => n.toString().padLeft(2, '0');
      return '${time.year}-${two(time.month)}-${two(time.day)} '
          '${two(time.hour)}:${two(time.minute)}:${two(time.second)}';
    }

    return AlertDialog(
      title: Text('${tr('Wireless clients')} — ${widget.device['name']}'),
      content: SizedBox(
        width: 1080,
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
                  'Clients keep their row order. Down means a complete registration check confirmed disconnection. Unknown means the current status could not be confirmed.',
                ),
              if (data!['history_limited'] == true)
                const AppText(
                  'Client history limit reached; some new clients are not shown.',
                ),
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
                    (data!['total'] as num) >
                        rows.where((row) => row['status'] == 'up').length)
                  Text(
                    '${rows.where((row) => row['status'] == 'up').length} confirmed up · ${rows.length} known clients',
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
                            'Status',
                            'Last seen',
                          ])
                            DataColumn(label: AppText(label)),
                        ],
                        rows: rows
                            .map(
                              (row) => DataRow(
                                key: ValueKey(row['mac_address']),
                                color: row['status'] == 'down'
                                    ? WidgetStatePropertyAll(
                                        Colors.red.withValues(alpha: .12),
                                      )
                                    : null,
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
                                  DataCell(
                                    Tooltip(
                                      message: row['status'] == 'unknown'
                                          ? 'Last confirmed: ${row['last_status'] ?? 'unknown'}'
                                          : 'Since ${localTime(row['status_since'])}',
                                      child: Text(
                                        row['status'] == 'up'
                                            ? 'Up'
                                            : row['status'] == 'down'
                                            ? 'Down'
                                            : 'Unknown',
                                        style: TextStyle(
                                          color: row['status'] == 'up'
                                              ? Colors.green
                                              : row['status'] == 'down'
                                              ? Colors.red
                                              : Colors.orange,
                                        ),
                                      ),
                                    ),
                                  ),
                                  DataCell(Text(localTime(row['last_seen']))),
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
