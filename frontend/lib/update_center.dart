import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'api.dart';

const updateFeedUrl =
    'https://github.com/safin97/airlink-isp-os/releases/latest/download/stable.json';

class UpdateCenter extends StatefulWidget {
  final Api api;
  const UpdateCenter({super.key, required this.api});

  @override
  State<UpdateCenter> createState() => _UpdateCenterState();
}

class _UpdateCenterState extends State<UpdateCenter> {
  Map<String, dynamic>? snapshot;
  String? error;
  String? message;
  String? phase;
  bool checking = false;
  bool busy = false;
  bool fetching = false;
  DateTime? lastAutomaticCheck;
  Timer? timer;

  Map get service => snapshot?['state'] as Map? ?? {};
  Map get installation => service['state'] as Map? ?? {};
  Map? get available => service['available'] as Map?;
  bool get configured => service['configured'] == true;
  bool get installSupported => service['install_supported'] != false;
  bool get recovering => installation['status'] == 'failed';
  bool get installing =>
      const {'queued', 'installing'}.contains(installation['status']);
  bool get restartPending => service['restart']?['pending'] == true;
  bool get restartSupported => service['restart_supported'] == true;
  bool get autoCheckDue =>
      lastAutomaticCheck == null ||
      DateTime.now().difference(lastAutomaticCheck!) >=
          const Duration(minutes: 5);

  @override
  void initState() {
    super.initState();
    refresh(check: true);
    timer = Timer.periodic(const Duration(seconds: 3), (tick) {
      if (busy || installing || restartPending || tick.tick % 10 == 0) {
        refresh(check: !busy && !installing && !restartPending && autoCheckDue);
      }
    });
  }

  @override
  void dispose() {
    timer?.cancel();
    super.dispose();
  }

  Future<void> refresh({bool check = false}) async {
    if (fetching || !mounted) return;
    fetching = true;
    if (check) setState(() => checking = true);
    try {
      var data = Map<String, dynamic>.from(
        await widget.api.request('/updates'),
      );
      if (!mounted) return;
      setState(() => snapshot = data);
      if (check &&
          data['state']?['configured'] == true &&
          data['state']?['state']?['status'] != 'installing') {
        lastAutomaticCheck = DateTime.now();
        await widget.api.request('/updates/check', method: 'POST', body: {});
        data = Map<String, dynamic>.from(await widget.api.request('/updates'));
      }
      if (!mounted) return;
      setState(() {
        snapshot = data;
        error = null;
      });
    } catch (e) {
      if (mounted && !busy) setState(() => error = e.toString());
    } finally {
      fetching = false;
      if (mounted) setState(() => checking = false);
    }
  }

  Future<void> restartSystem() async {
    if (!restartSupported ||
        busy ||
        installing ||
        recovering ||
        restartPending) {
      return;
    }
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const Text('Restart AirLink system?'),
        content: const Text(
          'This restarts the entire AirLink PC. Monitoring and the dashboard will be unavailable briefly. The page will reconnect when the server returns.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('Restart system'),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;
    setState(() {
      busy = true;
      error = null;
      message = null;
      phase = 'Requesting system restart…';
    });
    try {
      final accepted = await widget.api.request(
        '/system/restart',
        method: 'POST',
        body: {'confirm': true},
      );
      if (!mounted) return;
      final previousBoot = accepted['boot_id'];
      setState(
        () => phase = 'Restart requested. Waiting for the server to return…',
      );
      final deadline = DateTime.now().add(const Duration(minutes: 5));
      while (mounted && DateTime.now().isBefore(deadline)) {
        await Future<void>.delayed(const Duration(seconds: 3));
        if (!mounted) return;
        try {
          final data = Map<String, dynamic>.from(
            await widget.api.request('/updates'),
          );
          if (!mounted) return;
          setState(() => snapshot = data);
          final boot = data['state']?['restart']?['boot_id'];
          if (previousBoot != null && boot != null && boot != previousBoot) {
            setState(() => message = 'System restarted successfully.');
            return;
          }
        } catch (_) {
          // A disconnected API is expected during reboot, not proof of completion.
        }
      }
      if (mounted) {
        setState(
          () => message =
              'Restart is not yet confirmed. Check the AirLink PC before trying again.',
        );
      }
    } catch (e) {
      if (mounted) setState(() => error = e.toString());
    } finally {
      if (mounted) {
        setState(() {
          busy = false;
          phase = null;
        });
      }
    }
  }

  Future<void> updateNow() async {
    final release = available;
    if (release == null || busy || !installSupported) return;
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text('Update to ${release['version']}?'),
        content: const Text(
          'The server will download and verify the signed package, back up the database, and install the update. Monitoring pauses briefly while services restart.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('Update now'),
          ),
        ],
      ),
    );
    if (confirmed == true && mounted) {
      await runUpdate(Map<String, dynamic>.from(release));
    }
  }

  Future<void> scheduleUpdate() async {
    final release = available;
    if (release == null || busy || !installSupported) return;
    final controller = TextEditingController();
    final at = await showDialog<String>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text('Schedule ${release['version']}'),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Text(
              'The signed package will be downloaded and verified now. Monitoring pauses at the scheduled installation time.',
            ),
            const SizedBox(height: 12),
            TextField(
              controller: controller,
              decoration: const InputDecoration(
                labelText: 'Date and time with timezone',
                hintText: '2026-12-01T02:00:00+01:00',
              ),
            ),
          ],
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, controller.text.trim()),
            child: const Text('Schedule'),
          ),
        ],
      ),
    );
    controller.dispose();
    if (at == null || !mounted) return;
    final date = DateTime.tryParse(at);
    if (date == null ||
        !date.isAfter(DateTime.now()) ||
        !RegExp(r'(Z|[+-]\d{2}:\d{2})$').hasMatch(at)) {
      setState(
        () => error = 'Enter a future date and time including its timezone.',
      );
      return;
    }
    await runUpdate(Map<String, dynamic>.from(release), at: at);
  }

  Future<void> runUpdate(Map<String, dynamic> release, {String? at}) async {
    final expected = {
      'version': release['version'],
      'sequence': release['sequence'],
    };
    final previousFinish = installation['finished'];
    setState(() {
      busy = true;
      error = null;
      message = null;
      phase = 'Downloading signed update…';
    });
    try {
      await widget.api.request(
        '/updates/download',
        method: 'POST',
        body: expected,
      );
      if (!mounted) return;
      setState(() => phase = 'Verifying package…');
      await widget.api.request(
        '/updates/verify',
        method: 'POST',
        body: expected,
      );
      if (!mounted) return;
      if (at != null) {
        await widget.api.request(
          '/updates/schedule',
          method: 'POST',
          body: {...expected, 'at': at},
        );
        if (mounted) {
          setState(() => message = 'Verified update scheduled for $at.');
        }
        return;
      }
      setState(() => phase = 'Starting installation…');
      await widget.api.request(
        '/updates/install',
        method: 'POST',
        body: expected,
      );
      final deadline = DateTime.now().add(const Duration(minutes: 30));
      while (mounted && DateTime.now().isBefore(deadline)) {
        await Future<void>.delayed(const Duration(seconds: 2));
        if (!mounted) return;
        Map<String, dynamic> data;
        try {
          data = Map<String, dynamic>.from(
            await widget.api.request('/updates'),
          );
        } catch (_) {
          if (mounted) {
            setState(() => phase = 'Reconnecting while services restart…');
          }
          continue;
        }
        if (!mounted) return;
        setState(() => snapshot = data);
        final status = data['state']?['state'] as Map? ?? {};
        if (status['status'] == 'failed' || status['status'] == 'rejected') {
          throw StateError(
            status['error']?.toString() ??
                'Installation failed. Review recovery information on the server.',
          );
        }
        if (status['status'] == 'installed' &&
            status['version'] == release['version'] &&
            status['finished'] != previousFinish) {
          setState(
            () => message = status['reboot_required'] == true
                ? 'Update installed. Restart the server when convenient.'
                : 'Update installed successfully.',
          );
          return;
        }
        setState(
          () => phase = status['status'] == 'installing'
              ? 'Installing update and checking services…'
              : 'Waiting for the installer to start…',
        );
      }
      if (mounted) {
        setState(
          () => message =
              'Installation has not reported completion. Check the server status; do not start another update.',
        );
      }
    } catch (e) {
      if (mounted) setState(() => error = e.toString());
    } finally {
      if (mounted) {
        setState(() {
          busy = false;
          phase = null;
        });
        // Poll status only: keep a failed-operation error visible to the owner.
        try {
          final data = Map<String, dynamic>.from(
            await widget.api.request('/updates'),
          );
          if (mounted) setState(() => snapshot = data);
        } catch (_) {}
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final release = available;
    final transfer = service['transfer'] as Map? ?? {};
    final total = (transfer['total'] as num?)?.toDouble() ?? 0;
    final received = (transfer['received'] as num?)?.toDouble() ?? 0;
    final progress =
        busy &&
            phase == 'Downloading signed update…' &&
            transfer['status'] == 'downloading' &&
            total > 0
        ? (received / total).clamp(0.0, 1.0)
        : null;
    final canInstall =
        configured &&
        installSupported &&
        release != null &&
        !busy &&
        !checking &&
        !installing &&
        !recovering &&
        !restartPending &&
        error == null;
    final canRestart =
        restartSupported &&
        !busy &&
        !checking &&
        !installing &&
        !recovering &&
        !restartPending;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          'Current version: ${snapshot?['current_version'] ?? (error == null ? 'Loading…' : 'Unavailable')}',
          style: Theme.of(context).textTheme.titleLarge,
        ),
        const SizedBox(height: 12),
        const Text(
          'Releases are fetched automatically from GitHub. Signed updates download and install here without opening another tab.',
        ),
        if (service['preview'] == true) ...[
          const SizedBox(height: 12),
          const Text(
            'Local preview: release checks are live. Install updates or restart from the dashboard hosted on your AirLink PC.',
          ),
        ],
        if (snapshot != null && !configured) ...[
          const SizedBox(height: 12),
          const Text(
            'Install the trusted publisher configuration on this appliance before checking for updates.',
          ),
        ],
        const SizedBox(height: 20),
        if (checking) const LinearProgressIndicator(),
        if (error != null)
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 12),
            child: Text(
              error!,
              style: TextStyle(color: Theme.of(context).colorScheme.error),
            ),
          ),
        if (message != null)
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 12),
            child: Text(message!),
          ),
        if (release != null) ...[
          Text(
            'Available release: ${release['version']}',
            style: Theme.of(context).textTheme.titleMedium,
          ),
          const SizedBox(height: 8),
          Text(
            '${((release['size'] as num? ?? 0) / (1024 * 1024)).toStringAsFixed(1)} MB · Signature verified',
          ),
          const SizedBox(height: 12),
          Text(
            release['reboot_required'] == true
                ? 'A restart is required after installation.'
                : 'No restart required.',
          ),
        ] else if (error == null &&
            service['last_check']?['up_to_date'] == true)
          const Text('You are up to date.'),
        if (recovering)
          Text(
            'The last installation failed. Review local recovery before retrying.',
            style: TextStyle(color: Theme.of(context).colorScheme.error),
          ),
        if (busy || installing || restartPending) ...[
          const SizedBox(height: 16),
          Text(
            phase ??
                (restartPending
                    ? 'System restart requested. Waiting for the server…'
                    : 'Installation is running on the server…'),
          ),
          const SizedBox(height: 8),
          LinearProgressIndicator(value: progress),
        ],
        const SizedBox(height: 20),
        Wrap(
          spacing: 12,
          runSpacing: 12,
          children: [
            FilledButton.icon(
              onPressed: canInstall ? updateNow : null,
              icon: const Icon(Icons.system_update_alt),
              label: const Text('Update now'),
            ),
            OutlinedButton(
              onPressed:
                  (configured || snapshot == null) &&
                      !busy &&
                      !checking &&
                      !installing
                  ? () => refresh(check: true)
                  : null,
              child: const Text('Check again'),
            ),
            OutlinedButton(
              onPressed: canInstall ? scheduleUpdate : null,
              child: const Text('Schedule update'),
            ),
            OutlinedButton.icon(
              onPressed: canRestart ? restartSystem : null,
              icon: const Icon(Icons.restart_alt),
              label: const Text('Restart system'),
            ),
          ],
        ),
        const SizedBox(height: 20),
        if (release != null)
          ExpansionTile(
            tilePadding: EdgeInsets.zero,
            title: const Text('Release notes'),
            children: [
              Align(
                alignment: Alignment.centerLeft,
                child: SelectableText(
                  release['release_notes']?.toString() ?? '',
                ),
              ),
            ],
          ),
        ExpansionTile(
          tilePadding: EdgeInsets.zero,
          title: const Text('Update source'),
          children: [
            const SelectableText(updateFeedUrl),
            TextButton.icon(
              onPressed: () async {
                await Clipboard.setData(
                  const ClipboardData(text: updateFeedUrl),
                );
                if (context.mounted) {
                  ScaffoldMessenger.of(context).showSnackBar(
                    const SnackBar(content: Text('Update URL copied')),
                  );
                }
              },
              icon: const Icon(Icons.copy_outlined),
              label: const Text('Copy URL'),
            ),
          ],
        ),
        const SizedBox(height: 20),
        Text('Update history', style: Theme.of(context).textTheme.titleMedium),
        const SizedBox(height: 8),
        if ((snapshot?['history'] as List? ?? []).isEmpty)
          const Text('No update actions recorded.'),
        for (final item in (snapshot?['history'] as List? ?? []))
          ListTile(
            title: Text('${item['version']} · ${item['status']}'),
            subtitle: Text(item['created_at'].toString()),
          ),
      ],
    );
  }
}
