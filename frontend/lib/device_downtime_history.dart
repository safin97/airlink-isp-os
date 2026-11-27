import 'dart:async';
import 'dart:convert';
import 'package:flutter/material.dart';
import 'api.dart';

class DeviceDowntimeHistoryDialog extends StatelessWidget {
  const DeviceDowntimeHistoryDialog({
    super.key,
    required this.api,
    required this.device,
  });
  final Api api;
  final Map<String, dynamic> device;

  @override
  Widget build(BuildContext context) => AlertDialog(
    title: Text('${device['name']} · ${device['ip_address']}'),
    content: SizedBox(
      width: 800,
      child: SingleChildScrollView(
        child: DeviceDowntimeHistory(api: api, deviceId: device['id']),
      ),
    ),
    actions: [
      TextButton(
        onPressed: () => Navigator.pop(context),
        child: const Text('Close'),
      ),
    ],
  );
}

class DeviceDowntimeHistory extends StatefulWidget {
  const DeviceDowntimeHistory({
    super.key,
    required this.api,
    required this.deviceId,
  });
  final Api api;
  final String deviceId;

  @override
  State<DeviceDowntimeHistory> createState() => _DeviceDowntimeHistoryState();
}

class _DeviceDowntimeHistoryState extends State<DeviceDowntimeHistory> {
  List<dynamic> outages = [];
  String? error;
  bool busy = false;
  bool fetching = false;
  int generation = 0;
  Timer? timer;

  @override
  void initState() {
    super.initState();
    load();
    timer = Timer.periodic(const Duration(seconds: 15), (_) {
      if (!busy) load(quiet: true);
    });
  }

  @override
  void didUpdateWidget(covariant DeviceDowntimeHistory oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.deviceId != widget.deviceId) {
      outages = [];
      load();
    }
  }

  @override
  void dispose() {
    timer?.cancel();
    super.dispose();
  }

  Future<void> load({bool quiet = false}) async {
    if (quiet && fetching) return;
    fetching = true;
    final request = ++generation;
    if (!quiet) {
      setState(() {
        busy = true;
        error = null;
      });
    }
    try {
      final result = await widget.api.request(
        '/devices/${Uri.encodeComponent(widget.deviceId)}/outages?limit=100&include_current=true',
      );
      if (mounted &&
          request == generation &&
          (error != null || jsonEncode(outages) != jsonEncode(result))) {
        setState(() {
          outages = List<dynamic>.from(result);
          error = null;
        });
      }
    } catch (e) {
      if (mounted && request == generation) {
        setState(() {
          error = e.toString();
          if (!quiet) outages = [];
        });
      }
    } finally {
      if (request == generation) fetching = false;
      if (mounted && request == generation && busy) {
        setState(() => busy = false);
      }
    }
  }

  String timestamp(dynamic value) {
    final date = DateTime.tryParse(value?.toString() ?? '')?.toLocal();
    if (date == null) return 'Unavailable';
    String pad(int value) => value.toString().padLeft(2, '0');
    return '${date.year}-${pad(date.month)}-${pad(date.day)} ${pad(date.hour)}:${pad(date.minute)}:${pad(date.second)}';
  }

  String duration(dynamic value) {
    if (value is! num) return 'Unavailable';
    final seconds = value.toInt();
    return '${seconds ~/ 60} min ${seconds % 60} sec';
  }

  @override
  Widget build(BuildContext context) => Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    children: [
      Row(
        children: [
          const Expanded(
            child: Text(
              'Downtime history',
              style: TextStyle(fontSize: 18, fontWeight: FontWeight.w600),
            ),
          ),
          IconButton(
            tooltip: 'Refresh downtime history',
            onPressed: busy ? null : load,
            icon: const Icon(Icons.refresh),
          ),
        ],
      ),
      const Text(
        'Each confirmed outage shows when the device went down and how long it lasted. Latest 100 completed outages plus any ongoing outage; times use your local clock (24-hour).',
      ),
      if (busy) const LinearProgressIndicator(),
      if (error != null)
        Text(
          error!,
          style: TextStyle(color: Theme.of(context).colorScheme.error),
        ),
      if (!busy && error == null && outages.isEmpty)
        const Padding(
          padding: EdgeInsets.symmetric(vertical: 12),
          child: Text('No confirmed outages recorded yet.'),
        ),
      if (outages.isNotEmpty)
        SingleChildScrollView(
          scrollDirection: Axis.horizontal,
          child: DataTable(
            columns: const [
              DataColumn(label: Text('Went down')),
              DataColumn(label: Text('Back online')),
              DataColumn(label: Text('Downtime (minutes)')),
            ],
            rows: outages
                .map(
                  (outage) => DataRow(
                    cells: [
                      DataCell(Text(timestamp(outage['started_at']))),
                      DataCell(
                        Text(
                          outage['ended_at'] == null
                              ? 'Still down'
                              : timestamp(outage['ended_at']),
                        ),
                      ),
                      DataCell(Text(duration(outage['duration_seconds']))),
                    ],
                  ),
                )
                .toList(),
          ),
        ),
    ],
  );
}
