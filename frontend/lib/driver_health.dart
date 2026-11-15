import 'package:flutter/material.dart';

class DriverHealth extends StatefulWidget {
  const DriverHealth({super.key, this.data, this.loading = false});
  final Map<String, dynamic>? data;
  final bool loading;

  @override
  State<DriverHealth> createState() => _DriverHealthState();
}

class _DriverHealthState extends State<DriverHealth> {
  String query = '';
  String status = 'all';

  List<Map<String, dynamic>> items(String key) =>
      List<Map<String, dynamic>>.from(widget.data?[key] ?? []);

  bool matches(Map<String, dynamic> item) =>
      (status == 'all' || item['status'] == status) &&
      [
        'name',
        'id',
        'category',
        'driver',
        'module',
        'version',
      ].any((key) => '${item[key] ?? ''}'.toLowerCase().contains(query));

  Widget badge(String value) {
    final (label, icon, color) = switch (value) {
      'loaded' => ('Loaded', Icons.check_circle_outline, Colors.green),
      'warning' => ('Needs attention', Icons.warning_amber, Colors.orange),
      _ => ('Unknown', Icons.help_outline, Colors.blueGrey),
    };
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Icon(icon, size: 18, color: color),
        const SizedBox(width: 5),
        Text(label),
      ],
    );
  }

  @override
  Widget build(BuildContext context) {
    final data = widget.data;
    final devices = items('devices').where(matches).toList();
    final modules = items('modules').where(matches).toList();
    final counts = Map<String, dynamic>.from(data?['counts'] ?? {});
    final available = data != null && data['status'] != 'unavailable';
    final checked = DateTime.tryParse('${data?['checked_at']}')?.toLocal();
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            const Text(
              'Drivers & device health',
              style: TextStyle(fontSize: 20, fontWeight: FontWeight.w600),
            ),
            const SizedBox(height: 8),
            const Text(
              'Loaded means the driver is active. It does not guarantee good performance or the latest version. Unknown means there is not enough information to judge.',
            ),
            if (checked != null) Text('Last checked: $checked'),
            if (data?['kernel'] != null)
              Text('Running kernel: ${data!['kernel']}'),
            if (!available)
              Padding(
                padding: const EdgeInsets.only(top: 12),
                child: Text(
                  widget.loading
                      ? 'Checking drivers…'
                      : '${data?['note'] ?? 'Driver information is unavailable. Refresh diagnostics on the installed AirLink PC.'}',
                ),
              ),
            if (available) ...[
              const SizedBox(height: 12),
              Wrap(
                spacing: 8,
                runSpacing: 8,
                children: [
                  Chip(label: Text('${counts['loaded'] ?? 0} loaded')),
                  Chip(label: Text('${counts['warning'] ?? 0} need attention')),
                  Chip(label: Text('${counts['unknown'] ?? 0} unknown')),
                ],
              ),
              if (data['truncated'] == true)
                const Text(
                  'Partial inventory: the scan reached its time or size limit. Refresh to check again.',
                ),
              const SizedBox(height: 12),
              TextField(
                decoration: const InputDecoration(
                  labelText: 'Search devices or drivers',
                  prefixIcon: Icon(Icons.search),
                  border: OutlineInputBorder(),
                ),
                onChanged: (value) =>
                    setState(() => query = value.trim().toLowerCase()),
              ),
              const SizedBox(height: 8),
              Wrap(
                spacing: 8,
                children: [
                  for (final entry in const {
                    'all': 'All',
                    'warning': 'Needs attention',
                    'unknown': 'Unknown',
                    'loaded': 'Loaded',
                  }.entries)
                    ChoiceChip(
                      label: Text(entry.value),
                      selected: status == entry.key,
                      onSelected: (_) => setState(() => status = entry.key),
                    ),
                ],
              ),
              const SizedBox(height: 12),
              Text('Detected devices (${devices.length})'),
              if (devices.isEmpty)
                const Padding(
                  padding: EdgeInsets.all(12),
                  child: Text('No matching devices.'),
                )
              else
                SizedBox(
                  height: devices.length == 1 ? 230 : 420,
                  child: ListView.builder(
                    key: const ValueKey('driver-device-list'),
                    itemCount: devices.length,
                    itemBuilder: (context, index) {
                      final item = devices[index];
                      return Padding(
                        padding: const EdgeInsets.symmetric(vertical: 12),
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              '${item['name']}',
                              style: const TextStyle(
                                fontWeight: FontWeight.w600,
                              ),
                            ),
                            badge('${item['status']}'),
                            Text('${item['category']} · ${item['id']}'),
                            Text('Driver: ${item['driver'] ?? 'Not reported'}'),
                            if (item['module'] != null)
                              Text('Module: ${item['module']}'),
                            Text(
                              'Version: ${item['version'] ?? 'Not separately reported; see running kernel'}',
                            ),
                            Text('${item['detail']}'),
                            for (final metric in item['metrics'] ?? [])
                              Text('$metric'),
                            const Divider(),
                          ],
                        ),
                      );
                    },
                  ),
                ),
              ExpansionTile(
                tilePadding: EdgeInsets.zero,
                title: Text('Loaded kernel components (${modules.length})'),
                subtitle: const Text(
                  'Includes built-in drivers and modules without a device binding.',
                ),
                children: [
                  if (modules.isEmpty)
                    const Text('No matching kernel components.'),
                  if (modules.isNotEmpty)
                    SizedBox(
                      height: 300,
                      child: ListView.builder(
                        key: const ValueKey('driver-module-list'),
                        itemCount: modules.length,
                        itemBuilder: (context, index) {
                          final item = modules[index];
                          return ListTile(
                            title: Wrap(
                              spacing: 12,
                              children: [
                                Text('${item['name']}'),
                                badge('${item['status']}'),
                              ],
                            ),
                            subtitle: Text(
                              'Version: ${item['version'] ?? 'Not separately reported'}\n${item['detail']}',
                            ),
                          );
                        },
                      ),
                    ),
                ],
              ),
            ],
          ],
        ),
      ),
    );
  }
}
