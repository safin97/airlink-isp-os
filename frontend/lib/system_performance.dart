import 'package:flutter/material.dart';
import 'app_language.dart';

class SystemPerformance extends StatelessWidget {
  final Map<String, dynamic> data;
  const SystemPerformance({super.key, required this.data});

  String number(dynamic value, {String suffix = ''}) =>
      value is num ? '${value.toStringAsFixed(1)}$suffix' : 'Unavailable';

  String bytes(dynamic value) {
    if (value is! num) return 'Unavailable';
    if (value >= 1073741824) {
      return '${(value / 1073741824).toStringAsFixed(1)} GiB';
    }
    return '${(value / 1048576).toStringAsFixed(1)} MiB';
  }

  String throughput(dynamic value) => value is num
      ? '${(value / 1048576).toStringAsFixed(2)} MiB/s'
      : 'Unavailable';

  @override
  Widget build(BuildContext context) {
    final theme = Theme.of(context);
    final memory = data['memory'] as Map? ?? {};
    final storage = data['storage'] as Map? ?? {};
    final cards = <Widget>[];
    Widget tile(
      String title,
      IconData icon,
      String reading,
      List<String> details, {
      dynamic percent,
    }) => Card(
      margin: EdgeInsets.zero,
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Icon(icon, size: 20, color: theme.colorScheme.primary),
                const SizedBox(width: 8),
                Expanded(
                  child: AppText(
                    title,
                    style: const TextStyle(fontWeight: FontWeight.w600),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 12),
            Text(
              reading,
              style: const TextStyle(fontSize: 24, fontWeight: FontWeight.w600),
            ),
            if (percent is num) ...[
              const SizedBox(height: 10),
              LinearProgressIndicator(
                value: (percent / 100).clamp(0.0, 1.0).toDouble(),
              ),
            ],
            const SizedBox(height: 10),
            ...details.map(
              (text) => Padding(
                padding: const EdgeInsets.only(top: 3),
                child: Text(text, style: theme.textTheme.bodySmall),
              ),
            ),
          ],
        ),
      ),
    );
    cards.add(
      tile('CPU', Icons.memory, number(data['cpu_percent'], suffix: '%'), [
        'Clock: ${number(data['cpu_mhz'], suffix: ' MHz')}',
        '${data['cpu_cores'] ?? '—'} cores · ${data['cpu_threads'] ?? '—'} threads',
      ], percent: data['cpu_percent']),
    );
    cards.add(
      tile('Memory', Icons.storage, number(memory['percent'], suffix: '%'), [
        '${bytes(memory['used_bytes'])} used / ${bytes(memory['total_bytes'])}',
        '${bytes(memory['available_bytes'])} available',
      ], percent: memory['percent']),
    );
    cards.add(
      tile(
        'Storage',
        Icons.dns_outlined,
        number(storage['percent'], suffix: '%'),
        [
          '${bytes(storage['used_bytes'])} used / ${bytes(storage['total_bytes'])}',
          '${bytes(storage['free_bytes'])} free · system volume',
        ],
        percent: storage['percent'],
      ),
    );
    cards.add(
      tile(
        'Disk activity',
        Icons.swap_vert,
        throughput(data['disk_read_bytes_sec']),
        ['Read speed', 'Write: ${throughput(data['disk_write_bytes_sec'])}'],
      ),
    );
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const AppText(
          'PC performance',
          style: TextStyle(fontSize: 22, fontWeight: FontWeight.w600),
        ),
        const SizedBox(height: 6),
        Text(
          data['status'] == 'stale'
              ? 'Performance readings are out of date.'
              : '${data['hostname'] ?? 'This PC'} · ${data['platform'] ?? 'System'}'
                    ' · Updates every 30 seconds',
          style: theme.textTheme.bodySmall,
        ),
        const SizedBox(height: 12),
        LayoutBuilder(
          builder: (context, constraints) {
            final count = constraints.maxWidth >= 1100
                ? 4
                : constraints.maxWidth >= 700
                ? 3
                : constraints.maxWidth >= 460
                ? 2
                : 1;
            final width = (constraints.maxWidth - (count - 1) * 12) / count;
            return Wrap(
              spacing: 12,
              runSpacing: 12,
              children: cards
                  .map((card) => SizedBox(width: width, child: card))
                  .toList(),
            );
          },
        ),
      ],
    );
  }
}
