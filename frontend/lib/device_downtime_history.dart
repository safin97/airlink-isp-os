import 'dart:async';
import 'package:flutter/material.dart';
import 'api.dart';

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
  int generation = 0;
  Timer? timer;

  @override
  void initState() {
    super.initState();
    load();
    timer = Timer.periodic(const Duration(seconds: 15), (_) {
      if (!busy) load();
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

  Future<void> load() async {
    final request = ++generation;
    setState(() {
      busy = true;
      error = null;
    });
    try {
      final result = await widget.api.request(
        '/devices/${Uri.encodeComponent(widget.deviceId)}/outages?limit=100',
      );
      if (mounted && request == generation) {
        setState(() => outages = List<dynamic>.from(result));
      }
    } catch (e) {
      if (mounted && request == generation) {
        setState(() {
          error = e.toString();
          outages = [];
        });
      }
    } finally {
      if (mounted && request == generation) setState(() => busy = false);
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
    return '${seconds ~/ 86400}d ${(seconds % 86400) ~/ 3600}h ${(seconds % 3600) ~/ 60}m ${seconds % 60}s';
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
        'Completed outages are saved when the device comes back online. Latest 100 outages; times are local.',
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
          child: Text('No completed outages recorded yet.'),
        ),
      if (outages.isNotEmpty)
        SingleChildScrollView(
          scrollDirection: Axis.horizontal,
          child: DataTable(
            columns: const [
              DataColumn(label: Text('Offline since')),
              DataColumn(label: Text('Back online')),
              DataColumn(label: Text('Downtime')),
            ],
            rows: outages
                .map(
                  (outage) => DataRow(
                    cells: [
                      DataCell(Text(timestamp(outage['started_at']))),
                      DataCell(Text(timestamp(outage['ended_at']))),
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
