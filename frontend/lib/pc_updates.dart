import 'dart:async';
import 'package:flutter/material.dart';
import 'api.dart';

class PcUpdates extends StatefulWidget {
  const PcUpdates({super.key, required this.api});
  final Api api;
  @override
  State<PcUpdates> createState() => _PcUpdatesState();
}

class _PcUpdatesState extends State<PcUpdates> {
  Map<String, dynamic>? data;
  String? error;
  bool loading = false;
  Timer? poll;
  static const running = {
    'queued_check',
    'checking',
    'queued_install',
    'installing',
  };

  @override
  void initState() {
    super.initState();
    load();
  }

  @override
  void dispose() {
    poll?.cancel();
    super.dispose();
  }

  void schedulePoll() {
    poll?.cancel();
    if (running.contains(data?['state']?['status'])) {
      poll = Timer(const Duration(seconds: 3), load);
    }
  }

  Future<void> load() async {
    if (loading) return;
    setState(() => loading = true);
    try {
      final result = await widget.api.request('/system/pc-updates');
      if (!mounted) return;
      setState(() {
        data = Map<String, dynamic>.from(result);
        error = null;
      });
    } catch (e) {
      if (mounted) setState(() => error = e.toString());
    } finally {
      if (mounted) {
        setState(() => loading = false);
        schedulePoll();
      }
    }
  }

  Future<void> act(
    String action, [
    Map<String, dynamic> body = const {},
  ]) async {
    poll?.cancel();
    setState(() {
      loading = true;
      error = null;
    });
    try {
      final result = await widget.api.request(
        '/system/pc-updates/$action',
        method: 'POST',
        body: body,
        retry: false,
      );
      if (mounted) setState(() => data = Map<String, dynamic>.from(result));
    } catch (e) {
      if (mounted) setState(() => error = e.toString());
    } finally {
      if (mounted) {
        setState(() => loading = false);
        schedulePoll();
      }
    }
  }

  Future<void> install(Map<String, dynamic> plan) async {
    final approved = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Install reviewed PC updates?'),
        content: Text(
          'Install ${plan['packages'].length} reviewed packages from the configured repositories. '
          'Monitoring or the dashboard may be interrupted. Keep the PC powered on. '
          'AirLink data is backed up before installation; automatic system rollback is unavailable. '
          'A restart is recommended afterward.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('Install updates'),
          ),
        ],
      ),
    );
    if (approved == true && mounted) {
      await act('install', {'confirm': true, 'plan_id': plan['id']});
    }
  }

  @override
  Widget build(BuildContext context) {
    final state = Map<String, dynamic>.from(data?['state'] ?? {});
    final plan = data?['plan'] == null
        ? null
        : Map<String, dynamic>.from(data!['plan']);
    final packages = List<Map<String, dynamic>>.from(plan?['packages'] ?? []);
    final busy = loading || running.contains(state['status']);
    final supported = data?['supported'] == true;
    final recovery = state['recovery_required'] == true;
    final label = switch (state['status']) {
      'queued_check' => 'Waiting to check online…',
      'checking' => 'Checking online repositories…',
      'queued_install' => 'Preparing and downloading reviewed updates…',
      'installing' => 'Installing PC updates. Keep the PC powered on.',
      'installed' => 'PC updates installed.',
      'ready' =>
        packages.isEmpty
            ? 'No applicable updates available.'
            : '${packages.length} updates ready for review',
      'failed' => 'PC update needs local recovery review.',
      'rejected' => 'PC update did not complete. Check the details below.',
      _ => 'Check for available driver and system updates.',
    };
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text(
              'PC & driver updates',
              style: TextStyle(fontSize: 20, fontWeight: FontWeight.w600),
            ),
            const SizedBox(height: 8),
            const Text(
              'Update installed GPU drivers, CPU microcode, Linux kernel, device firmware and system packages over the internet.',
            ),
            const Text(
              'Uses the PC’s configured repositories and driver branch. BIOS/UEFI firmware is not included.',
            ),
            const SizedBox(height: 12),
            if (data != null && !supported)
              Text('${data!['reason']}')
            else
              Text(label),
            if (busy) const LinearProgressIndicator(),
            if (error != null)
              Text(
                error!,
                style: TextStyle(color: Theme.of(context).colorScheme.error),
              ),
            if (state['error'] != null) Text('${state['error']}'),
            if (recovery)
              const Text(
                'An installation was interrupted or failed. Review the PC locally before another update or restart.',
              ),
            if (data?['reboot_required'] == true)
              const Text(
                'Restart recommended to activate updates. Open Software Updates → Restart system when ready.',
              ),
            if (packages.isNotEmpty) ...[
              const SizedBox(height: 12),
              SizedBox(
                height: packages.length > 5 ? 320 : packages.length * 72.0,
                child: ListView.builder(
                  itemCount: packages.length,
                  itemBuilder: (context, index) {
                    final p = packages[index];
                    return ListTile(
                      dense: true,
                      title: Text('${p['name']} · ${p['category']}'),
                      subtitle: Text(
                        '${p['installed'] ?? 'Not installed'} → ${p['candidate']}',
                      ),
                    );
                  },
                ),
              ),
            ],
            const SizedBox(height: 12),
            Wrap(
              spacing: 12,
              runSpacing: 8,
              children: [
                OutlinedButton.icon(
                  onPressed: !supported || busy || recovery
                      ? null
                      : () => act('check'),
                  icon: const Icon(Icons.system_update_alt),
                  label: const Text('Check online'),
                ),
                if (packages.isNotEmpty)
                  FilledButton(
                    onPressed: !supported || busy || recovery || error != null
                        ? null
                        : () => install(plan!),
                    child: const Text('Review and install'),
                  ),
                TextButton(
                  onPressed: loading ? null : load,
                  child: const Text('Refresh update status'),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}
