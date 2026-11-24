import 'section_access.dart';
import 'package:flutter/material.dart';
import 'dart:async';
import 'dart:convert';

import 'api.dart';
import 'app_language.dart';
import 'pc_updates.dart';
import 'driver_health.dart';

class DiagnosticsScreen extends StatefulWidget {
  const DiagnosticsScreen({super.key, required this.api});
  final Api api;

  @override
  State<DiagnosticsScreen> createState() => _DiagnosticsScreenState();
}

class _DiagnosticsScreenState extends State<DiagnosticsScreen> {
  Map<String, dynamic>? data;
  String? error;
  bool loading = true;
  bool fetching = false;
  Timer? timer;

  @override
  void initState() {
    super.initState();
    load();
    timer = Timer.periodic(
      const Duration(seconds: 10),
      (_) => load(quiet: true),
    );
  }

  @override
  void dispose() {
    timer?.cancel();
    super.dispose();
  }

  Future<void> load({bool quiet = false}) async {
    if (fetching) return;
    fetching = true;
    if (!quiet) {
      setState(() {
        loading = true;
        error = null;
      });
    }
    try {
      final result = await widget.api.request('/diagnostics');
      if (mounted &&
          (error != null || jsonEncode(data) != jsonEncode(result))) {
        setState(() {
          data = Map<String, dynamic>.from(result);
          error = null;
        });
      }
    } catch (e) {
      if (mounted) setState(() => error = e.toString());
    } finally {
      fetching = false;
      if (mounted && loading) setState(() => loading = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final problems = List<Map<String, dynamic>>.from(
      (data?['problems'] as List? ?? []).map(
        (item) => Map<String, dynamic>.from(item as Map),
      ),
    );
    final services = Map<String, dynamic>.from(data?['services'] as Map? ?? {});
    final resources = Map<String, dynamic>.from(
      data?['resources'] as Map? ?? {},
    );
    final update = Map<String, dynamic>.from(data?['update'] as Map? ?? {});
    final recent = List<String>.from(data?['recent_errors'] as List? ?? []);
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        Row(
          children: [
            Expanded(
              child: Text(
                data?['status'] == 'unavailable'
                    ? 'Appliance diagnostics unavailable in preview'
                    : data == null
                    ? (loading
                          ? 'Checking diagnostics…'
                          : 'Diagnostics unavailable')
                    : problems.isEmpty
                    ? 'No active problems detected'
                    : '${problems.length} active problem${problems.length == 1 ? '' : 's'}',
                style: const TextStyle(
                  fontSize: 20,
                  fontWeight: FontWeight.w600,
                ),
              ),
            ),
            OutlinedButton.icon(
              onPressed: loading ? null : load,
              icon: const Icon(Icons.refresh),
              label: const AppText('Refresh diagnostics'),
            ),
          ],
        ),
        if (loading) const LinearProgressIndicator(),
        if (error != null)
          Card(
            color: Theme.of(context).colorScheme.errorContainer,
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Text(error!),
            ),
          ),
        for (final problem in problems)
          Card(
            child: ListTile(
              leading: Icon(
                problem['severity'] == 'critical'
                    ? Icons.error_outline
                    : Icons.warning_amber_outlined,
                color: problem['severity'] == 'critical'
                    ? Colors.red
                    : Colors.orange,
              ),
              title: Text('${problem['title'] ?? 'Problem'}'),
              subtitle: Text('${problem['detail'] ?? ''}'),
              trailing: Text('${problem['source'] ?? ''}'),
            ),
          ),
        const SizedBox(height: 12),
        Wrap(
          spacing: 12,
          runSpacing: 12,
          children: [
            _summary('CPU', resources['cpu_percent'], '%'),
            _summary('Memory', resources['memory_percent'], '%'),
            _summary('Storage', resources['storage_percent'], '%'),
            _summary('Update state', update['status'] ?? 'unknown', ''),
          ],
        ),
        const SizedBox(height: 16),
        DriverHealth(
          data: data?['drivers'] == null
              ? null
              : Map<String, dynamic>.from(data!['drivers']),
          loading: loading,
        ),
        const SizedBox(height: 16),
        if (hasSection(widget.api.user ?? {}, 'pc_updates')) ...[
          PcUpdates(api: widget.api),
          const SizedBox(height: 16),
        ],
        _section(
          'Services',
          services.isEmpty
              ? ['Service status unavailable.']
              : services.entries
                    .map((entry) => '${entry.key}: ${entry.value}')
                    .toList(),
        ),
        const SizedBox(height: 16),
        _section(
          'Recent error-level system logs',
          data == null || data?['status'] == 'unavailable'
              ? ['System logs unavailable.']
              : recent.isEmpty
              ? ['No recent error-level AirLink logs.']
              : recent,
          monospace: true,
        ),
        if (update['recovery_required'] == true) ...[
          const SizedBox(height: 16),
          const Card(
            child: Padding(
              padding: EdgeInsets.all(16),
              child: AppText(
                'Recovery required: do not clear the failed update marker or retry until the installed package, database migration and update journal have been reviewed locally.',
              ),
            ),
          ),
        ],
      ],
    );
  }

  Widget _summary(String label, dynamic value, String suffix) => SizedBox(
    width: 180,
    child: Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(label),
            const SizedBox(height: 6),
            Text(
              value == null ? 'Unavailable' : '$value$suffix',
              style: const TextStyle(fontSize: 20, fontWeight: FontWeight.w600),
            ),
          ],
        ),
      ),
    ),
  );

  Widget _section(String title, List<String> lines, {bool monospace = false}) =>
      Card(
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                title,
                style: const TextStyle(
                  fontSize: 18,
                  fontWeight: FontWeight.w600,
                ),
              ),
              const SizedBox(height: 10),
              for (final line in lines)
                SelectableText(
                  line,
                  style: monospace
                      ? const TextStyle(fontFamily: 'monospace', fontSize: 12)
                      : null,
                ),
            ],
          ),
        ),
      );
}
