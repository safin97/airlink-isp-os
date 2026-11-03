import 'package:flutter/material.dart';
import 'api.dart';
import 'app_language.dart';

class OnlineDeviceDialog extends StatefulWidget {
  final Api api;
  final Map<String, dynamic> row;
  const OnlineDeviceDialog({super.key, required this.api, required this.row});

  @override
  State<OnlineDeviceDialog> createState() => _OnlineDeviceDialogState();
}

class _OnlineDeviceDialogState extends State<OnlineDeviceDialog> {
  Map<String, dynamic>? data;
  String? error;
  bool busy = true;

  @override
  void initState() {
    super.initState();
    load();
  }

  Future<void> load() async {
    setState(() {
      busy = true;
      error = null;
    });
    try {
      final query = Uri(
        queryParameters: {
          'username': '${widget.row['username']}',
          'ip_address': '${widget.row['ip_address']}',
          if (widget.row['session_id'] != null)
            'session_id': '${widget.row['session_id']}',
        },
      ).query;
      final result = await widget.api.request(
        '/integrations/sas4/online-device?$query',
      );
      if (mounted) {
        setState(() => data = Map<String, dynamic>.from(result));
      }
    } catch (e) {
      if (mounted) {
        setState(() => error = e.toString());
      }
    } finally {
      if (mounted) {
        setState(() => busy = false);
      }
    }
  }

  String value(dynamic item, [String suffix = '']) =>
      item == null || '$item'.isEmpty ? tr('Unavailable') : '$item$suffix';

  Widget section(
    String title,
    List<dynamic> rows,
    List<String> labels,
    List<String> Function(dynamic) cells,
    String empty,
  ) {
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            AppText(title, style: Theme.of(context).textTheme.titleMedium),
            const SizedBox(height: 8),
            if (rows.isEmpty)
              AppText(empty)
            else
              SingleChildScrollView(
                scrollDirection: Axis.horizontal,
                child: DataTable(
                  horizontalMargin: 0,
                  columnSpacing: 24,
                  columns: [
                    for (final label in labels)
                      DataColumn(label: AppText(label)),
                  ],
                  rows: [
                    for (final row in rows)
                      DataRow(
                        cells: [
                          for (final text in cells(row))
                            DataCell(SelectableText(text)),
                        ],
                      ),
                  ],
                ),
              ),
          ],
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) => AlertDialog(
    title: AppText('Device • ${widget.row['username']}'),
    content: SizedBox(
      width: 860,
      child: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            SelectableText('${widget.row['ip_address']}'),
            if (busy) ...[
              const SizedBox(height: 12),
              const LinearProgressIndicator(),
              const AppText('Connecting to device…'),
            ],
            if (error != null)
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 12),
                child: Text(
                  error!,
                  style: TextStyle(color: Theme.of(context).colorScheme.error),
                ),
              ),
            if (data != null) ...[
              Text(
                '${data!['vendor']} • ${tr('Saved login')}: ${data!['credential_source']}',
              ),
              if (error != null)
                const AppText('Showing the previous readings.'),
              section(
                'Wireless',
                data!['wireless'] as List? ?? [],
                ['Interface', 'SSID', 'Signal', 'Status'],
                (r) => [
                  value(r['name']),
                  value(r['ssid']),
                  value(r['signal_dbm'], ' dBm'),
                  value(r['status']),
                ],
                'No wireless readings available.',
              ),
              section(
                'Ethernet ports',
                data!['ethernet'] as List? ?? [],
                ['Port', 'Status', 'Speed'],
                (r) => [
                  value(r['name']),
                  value(r['status']),
                  value(r['speed_mbps'], ' Mbps'),
                ],
                'No Ethernet readings available.',
              ),
              section(
                'PPPoE',
                data!['pppoe'] as List? ?? [],
                [
                  'Name',
                  'Username',
                  'Interface',
                  'Status',
                  'Uptime',
                  'Local IP',
                  'Remote IP',
                ],
                (r) => [
                  value(r['name']),
                  value(r['username']),
                  value(r['interface']),
                  value(r['status']),
                  value(r['uptime']),
                  value(r['local-address']),
                  value(r['remote-address']),
                ],
                data!['pppoe_note']?.toString() ??
                    'No PPPoE client interfaces configured.',
              ),
            ],
          ],
        ),
      ),
    ),
    actions: [
      TextButton(
        onPressed: busy ? null : load,
        child: const AppText('Refresh'),
      ),
      TextButton(
        onPressed: () => Navigator.pop(context),
        child: const AppText('Close'),
      ),
    ],
  );
}
