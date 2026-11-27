import 'dart:async';
import 'package:flutter/material.dart';
import 'api.dart';

class SshSettings extends StatefulWidget {
  const SshSettings({super.key, required this.api});
  final Api api;
  @override
  State<SshSettings> createState() => _SshSettingsState();
}

class _SshSettingsState extends State<SshSettings> {
  final sources = TextEditingController();
  final ownerPassword = TextEditingController();
  Map<String, dynamic>? data;
  String? error;
  bool busy = false;
  bool loading = false;
  int generation = 0;
  Timer? timer;

  @override
  void initState() {
    super.initState();
    if (widget.api.user?['role'] == 'owner') load();
  }

  @override
  void dispose() {
    timer?.cancel();
    sources.dispose();
    ownerPassword.dispose();
    super.dispose();
  }

  Future<void> load() async {
    if (loading || busy) return;
    loading = true;
    final started = generation;
    try {
      final result = Map<String, dynamic>.from(
        await widget.api.request('/system/ssh'),
      );
      if (!mounted || started != generation) return;
      if (data == null) {
        final saved = List<String>.from(result['sources'] ?? []);
        sources.text = saved.isNotEmpty
            ? saved.join('\n')
            : result['client_ip'] as String? ?? '';
      }
      setState(() {
        data = result;
      });
    } catch (e) {
      if (mounted) setState(() => error = e.toString());
    } finally {
      loading = false;
      if (mounted && !busy) {
        timer?.cancel();
        timer = Timer(const Duration(seconds: 5), load);
      }
    }
  }

  Future<void> act(String action) async {
    if (busy) return;
    generation++;
    timer?.cancel();
    setState(() {
      busy = true;
      error = null;
    });
    try {
      final result = await widget.api.request(
        '/system/ssh/$action',
        method: 'POST',
        body: {
          'owner_password': ownerPassword.text,
          if (action == 'enable') ...{
            'sources': sources.text
                .split(RegExp(r'[\s,]+'))
                .where((s) => s.isNotEmpty)
                .toList(),
          },
        },
      );
      if (mounted) setState(() => data = Map<String, dynamic>.from(result));
    } catch (e) {
      if (mounted) setState(() => error = e.toString());
    } finally {
      if (mounted) {
        ownerPassword.clear();
        setState(() => busy = false);
        timer = Timer(const Duration(seconds: 5), load);
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    if (widget.api.user?['role'] != 'owner') return const SizedBox.shrink();
    final supported = data?['supported'] == true;
    final installed = data?['server_installed'] == true;
    final enabled = data?['enabled'] == true;
    final active = data?['active'] == true;
    final job = Map<String, dynamic>.from(data?['install'] ?? {});
    final installing = ['queued', 'installing'].contains(job['status']);
    final usable = supported && !busy && !installing;
    final origin = Api.base.isEmpty ? Uri.base : Uri.parse(Api.base);
    final host = origin.host.isEmpty ? 'AIRLINK_PC_IP' : origin.host;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        const Text(
          'SSH remote access',
          style: TextStyle(fontSize: 24, fontWeight: FontWeight.w600),
        ),
        const SizedBox(height: 12),
        const Text(
          'Connect with PuTTY or an SSH client to run commands on this AirLink PC. '
          'SSH uses your AirLink owner login password. Saving access links SSH to your owner account, '
          'and changes to that account’s password also update SSH.',
        ),
        const SizedBox(height: 16),
        if (busy || data == null || installing) const LinearProgressIndicator(),
        if (error != null)
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 8),
            child: Text(
              error!,
              style: TextStyle(color: Theme.of(context).colorScheme.error),
            ),
          ),
        if (data?['reason'] != null) Text('${data!['reason']}'),
        Card(
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  active
                      ? 'SSH is running'
                      : enabled
                      ? 'SSH is enabled but not running'
                      : 'SSH is disabled',
                ),
                const SizedBox(height: 8),
                SelectableText(
                  'PuTTY host: $host\nPort: 2742\nConnection type: SSH\nUsername: airlink-admin',
                ),
                const SizedBox(height: 8),
                SelectableText('ssh -p 2742 airlink-admin@$host'),
                Text(
                  'Password account: ${data?['password_account'] ?? widget.api.user?['username'] ?? 'Owner'}',
                ),
                const Text('Use the same login password for SSH and sudo -i.'),
                if (data?['password_sync_pending'] == true)
                  const Text(
                    'SSH password synchronization needs attention. Save SSH access with your current AirLink login password.',
                  ),
                if (data?['fingerprint'] != null) ...[
                  const SizedBox(height: 12),
                  const Text(
                    'Compare this host-key fingerprint with PuTTY on the first connection:',
                  ),
                  SelectableText('${data!['fingerprint']}'),
                ],
              ],
            ),
          ),
        ),
        const SizedBox(height: 16),
        if (supported && !installed) ...[
          const Text(
            'This installation needs the OpenSSH server component. Install it from the PC’s configured '
            'repositories, then enable SSH below. A failed PC update must be recovered first.',
          ),
          if (installing) const Text('Installing SSH component…'),
          if (job['error'] != null) Text('${job['error']}'),
          const SizedBox(height: 16),
        ],
        if (installed) ...[
          TextField(
            controller: sources,
            enabled: usable,
            minLines: 2,
            maxLines: 4,
            decoration: const InputDecoration(
              labelText: 'Allowed client IP addresses or subnets',
              hintText: '192.168.1.0/24\n203.0.113.10',
              border: OutlineInputBorder(),
              helperText:
                  'One per line. Prefilled with this browser’s IP on first setup.',
            ),
          ),
          const SizedBox(height: 16),
        ],
        if (supported) ...[
          TextField(
            controller: ownerPassword,
            enabled: usable,
            obscureText: true,
            autocorrect: false,
            enableSuggestions: false,
            decoration: const InputDecoration(
              labelText: 'Current AirLink owner password',
              border: OutlineInputBorder(),
            ),
          ),
          const SizedBox(height: 16),
          Wrap(
            spacing: 12,
            runSpacing: 12,
            children: [
              if (!installed)
                FilledButton(
                  onPressed: usable ? () => act('install') : null,
                  child: const Text('Install SSH component'),
                ),
              if (installed)
                FilledButton(
                  onPressed: usable ? () => act('enable') : null,
                  child: Text(
                    enabled ? 'Save SSH access' : 'Enable SSH on port 2742',
                  ),
                ),
              if (enabled)
                OutlinedButton(
                  onPressed: usable ? () => act('disable') : null,
                  child: const Text('Disable SSH'),
                ),
            ],
          ),
          const SizedBox(height: 12),
          const Text(
            'Saving changes restarts SSH sessions. If connecting through a router, '
            'its forwarding rule must send TCP port 2742 to this AirLink PC.',
          ),
        ],
      ],
    );
  }
}
