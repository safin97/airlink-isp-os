import 'package:flutter/material.dart';
import 'tower_marker.dart';

const _muted = Color(0xff99acc6);
const _green = Color(0xff34d399);
const _red = Color(0xffff7385);
const _orange = Color(0xffffb454);

/// Read-only wallboard. All data comes from the signed-in user's API scope.
class NocScreen extends StatelessWidget {
  final Map<String, dynamic> summary;
  final List<dynamic> towers, devices, alerts;
  final bool hasData, expanded;
  final VoidCallback toggleExpanded, openAlerts, openMonitoring;
  final ValueChanged<String> openTowerDevices;

  const NocScreen({
    super.key,
    required this.summary,
    required this.towers,
    required this.devices,
    required this.alerts,
    required this.hasData,
    required this.expanded,
    required this.toggleExpanded,
    required this.openAlerts,
    required this.openMonitoring,
    required this.openTowerDevices,
  });

  Color statusColor(dynamic status) => switch (status) {
    'online' => _green,
    'offline' || 'critical' => _red,
    'warning' => _orange,
    _ => _muted,
  };

  int priority(dynamic status) => switch (status) {
    'offline' || 'critical' => 0,
    'warning' => 1,
    'online' => 3,
    _ => 2,
  };

  Widget box(Widget child) => Card(
    margin: EdgeInsets.zero,
    child: Padding(padding: const EdgeInsets.all(20), child: child),
  );

  Widget status(dynamic value) => Text(
    (value ?? 'unknown').toString().toUpperCase(),
    style: TextStyle(
      color: statusColor(value),
      fontSize: 12,
      fontWeight: FontWeight.w700,
    ),
  );

  Widget heading(String title, VoidCallback action, String label) => Row(
    children: [
      Expanded(
        child: Text(
          title,
          style: const TextStyle(fontSize: 20, fontWeight: FontWeight.w600),
        ),
      ),
      TextButton(onPressed: action, child: Text(label)),
    ],
  );

  Widget grid(List<Widget> children, double minWidth) => LayoutBuilder(
    builder: (context, constraints) {
      final count = (constraints.maxWidth / minWidth).floor().clamp(1, 4);
      return Wrap(
        spacing: 16,
        runSpacing: 16,
        children: children
            .map(
              (child) => SizedBox(
                width: (constraints.maxWidth - (count - 1) * 16) / count,
                child: child,
              ),
            )
            .toList(),
      );
    },
  );

  @override
  Widget build(BuildContext context) {
    final orderedTowers = [...towers]
      ..sort((a, b) => priority(a['status']).compareTo(priority(b['status'])));
    final attention =
        devices.where((device) => device['status'] != 'online').toList()..sort(
          (a, b) => priority(a['status']).compareTo(priority(b['status'])),
        );
    final active =
        alerts.where((alert) => alert['resolved_at'] == null).toList()..sort(
          (a, b) => priority(a['severity']).compareTo(priority(b['severity'])),
        );
    final metrics = [
      ('Online devices', 'online', _green),
      ('Offline devices', 'offline', _red),
      ('Unknown devices', 'unknown', _muted),
      ('Active alerts', 'active_alerts', _orange),
    ];
    final devicesById = {for (final device in devices) device['id']: device};
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Wrap(
          alignment: WrapAlignment.spaceBetween,
          spacing: 24,
          runSpacing: 12,
          children: [
            const Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  'Network operations center',
                  style: TextStyle(fontSize: 28, fontWeight: FontWeight.w700),
                ),
                SizedBox(height: 8),
                Text(
                  'Live network health • Unknown means no recent telemetry',
                  style: TextStyle(color: _muted),
                ),
              ],
            ),
            if (MediaQuery.sizeOf(context).width >= 1050)
              OutlinedButton.icon(
                onPressed: toggleExpanded,
                icon: Icon(
                  expanded ? Icons.close_fullscreen : Icons.open_in_full,
                ),
                label: Text(expanded ? 'Show sidebar' : 'Expand NOC'),
              ),
          ],
        ),
        const SizedBox(height: 24),
        grid(
          metrics
              .map(
                (metric) => box(
                  Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(metric.$1, style: const TextStyle(color: _muted)),
                      const SizedBox(height: 12),
                      Text(
                        hasData ? '${summary[metric.$2] ?? '—'}' : '—',
                        style: TextStyle(
                          fontSize: 46,
                          fontWeight: FontWeight.w700,
                          color: metric.$3,
                        ),
                      ),
                    ],
                  ),
                ),
              )
              .toList(),
          220,
        ),
        const SizedBox(height: 24),
        box(
          Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                'Tower status · ${towers.length}',
                style: const TextStyle(
                  fontSize: 20,
                  fontWeight: FontWeight.w600,
                ),
              ),
              const SizedBox(height: 18),
              if (towers.isEmpty)
                Text(
                  hasData
                      ? 'No towers in your authorized inventory yet.'
                      : 'Waiting for network data…',
                  style: const TextStyle(color: _muted),
                )
              else
                grid(
                  orderedTowers.map((tower) {
                    final members = devices
                        .where((device) => device['tower_id'] == tower['id'])
                        .toList();
                    return Material(
                      shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(12),
                        side: BorderSide(
                          color: statusColor(
                            tower['status'],
                          ).withValues(alpha: .5),
                        ),
                      ),
                      color: const Color(0xff071426),
                      clipBehavior: Clip.antiAlias,
                      child: InkWell(
                        onTap: () => openTowerDevices(tower['id']),
                        child: Padding(
                          padding: const EdgeInsets.all(16),
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Row(
                                children: [
                                  TowerMarker(
                                    statusColor: statusColor(tower['status']),
                                    size: 32,
                                  ),
                                  const SizedBox(width: 10),
                                  Expanded(
                                    child: Text(
                                      '${tower['name']}',
                                      style: const TextStyle(
                                        fontSize: 18,
                                        fontWeight: FontWeight.w600,
                                      ),
                                    ),
                                  ),
                                ],
                              ),
                              const SizedBox(height: 8),
                              const Text(
                                'View devices →',
                                style: TextStyle(
                                  color: Color(0xff438fff),
                                  fontSize: 12,
                                ),
                              ),
                              const SizedBox(height: 12),
                              status(tower['status']),
                              const SizedBox(height: 8),
                              Text(
                                '${members.length} devices · ${members.where((d) => d['status'] == 'offline').length} offline',
                                style: const TextStyle(color: _muted),
                              ),
                            ],
                          ),
                        ),
                      ),
                    );
                  }).toList(),
                  250,
                ),
            ],
          ),
        ),
        const SizedBox(height: 24),
        box(
          Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              heading('Active incidents', openAlerts, 'View alerts'),
              if (active.isEmpty)
                Padding(
                  padding: const EdgeInsets.symmetric(vertical: 16),
                  child: Text(
                    !hasData
                        ? 'Waiting for network data…'
                        : (summary['active_alerts'] ?? 0) > 0
                        ? 'Active alerts are reported outside the latest alert records.'
                        : 'No active alerts reported.',
                    style: const TextStyle(color: _muted),
                  ),
                )
              else
                ...active
                    .take(8)
                    .map(
                      (alert) => ListTile(
                        contentPadding: EdgeInsets.zero,
                        leading: Icon(
                          Icons.error_outline,
                          color: statusColor(alert['severity']),
                        ),
                        title: Text('${alert['message'] ?? 'Network alert'}'),
                        subtitle: Text(
                          '${devicesById[alert['device_id']]?['name'] ?? 'Device'} · ${alert['acknowledged_by'] == null ? 'Open' : 'Acknowledged'}',
                          style: const TextStyle(color: _muted),
                        ),
                        trailing: status(alert['severity']),
                      ),
                    ),
              if (active.length > 8)
                Text(
                  'Showing 8 of ${active.length} loaded active incidents.',
                  style: const TextStyle(color: _muted),
                ),
            ],
          ),
        ),
        const SizedBox(height: 24),
        box(
          Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              heading(
                'Devices needing attention',
                openMonitoring,
                'Monitoring',
              ),
              if (attention.isEmpty)
                Padding(
                  padding: const EdgeInsets.symmetric(vertical: 16),
                  child: Text(
                    !hasData
                        ? 'Waiting for network data…'
                        : devices.isEmpty
                        ? 'No monitored devices yet.'
                        : 'All monitored devices report online.',
                    style: const TextStyle(color: _muted),
                  ),
                )
              else
                ...attention
                    .take(12)
                    .map(
                      (device) => ListTile(
                        contentPadding: EdgeInsets.zero,
                        leading: Icon(
                          Icons.router_outlined,
                          color: statusColor(device['status']),
                        ),
                        title: Text('${device['name']}'),
                        subtitle: Text(
                          '${device['ip_address'] ?? 'No address'}',
                          style: const TextStyle(color: _muted),
                        ),
                        trailing: status(device['status']),
                      ),
                    ),
              if (attention.length > 12)
                Text(
                  'Showing 12 of ${attention.length} devices needing attention.',
                  style: const TextStyle(color: _muted),
                ),
            ],
          ),
        ),
      ],
    );
  }
}
