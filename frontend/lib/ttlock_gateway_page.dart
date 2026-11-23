import 'package:flutter/material.dart';
import 'package:lucide_icons_flutter/lucide_icons.dart';
import 'api.dart';
import 'ttlock_style.dart';

class TTLockGatewayPage extends StatefulWidget {
  final Api api;
  final int page;
  const TTLockGatewayPage({super.key, required this.api, required this.page});
  @override
  State<TTLockGatewayPage> createState() => _TTLockGatewayPageState();
}

class _TTLockGatewayPageState extends State<TTLockGatewayPage> {
  bool loading = true;
  String? error;
  List<Map<String, dynamic>> locks = [];
  @override
  void initState() {
    super.initState();
    load();
  }

  Future<void> load() async {
    setState(() {
      loading = true;
      error = null;
    });
    try {
      final data = await widget.api.request(
        '/integrations/ttlock/locks?page=${widget.page}',
      );
      if (mounted) {
        setState(
          () => locks = (data['items'] as List)
              .map((e) => Map<String, dynamic>.from(e))
              .toList(),
        );
      }
    } catch (e) {
      if (mounted) setState(() => error = e.toString());
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }

  @override
  Widget build(BuildContext context) => TTTheme(
    child: Builder(
      builder: (context) => Scaffold(
        appBar: AppBar(
          title: const Text('Gateway Management'),
          actions: [
            IconButton(
              onPressed: loading ? null : load,
              tooltip: 'Refresh gateways',
              icon: const Icon(LucideIcons.refreshCw),
            ),
          ],
        ),
        body: ListView(
          padding: const EdgeInsets.all(24),
          children: [
            const TTEmpty(
              title: 'Gateway visibility',
              message:
                  'The current integration reports whether a lock has a linked gateway. It does not expose gateway inventory, IDs, online status or last connection times. A linked gateway does not guarantee remote unlocking.',
              icon: LucideIcons.router,
            ),
            const SizedBox(height: 20),
            Wrap(
              spacing: 12,
              runSpacing: 12,
              children: [
                for (final s in [
                  'Add gateway',
                  'Edit gateway',
                  'Remove gateway',
                ])
                  Tooltip(
                    message:
                        'Gateway administration is not exposed by the existing integration.',
                    child: OutlinedButton(onPressed: null, child: Text(s)),
                  ),
              ],
            ),
            const SizedBox(height: 24),
            Text(
              'Lock connections · account page ${widget.page}',
              style: Theme.of(context).textTheme.titleLarge,
            ),
            const SizedBox(height: 16),
            if (loading) const TTSkeleton(),
            if (error != null)
              Text(error!, style: const TextStyle(color: ttRed)),
            for (final l in locks)
              Padding(
                padding: const EdgeInsets.only(bottom: 14),
                child: TTPanel(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        children: [
                          const Icon(LucideIcons.router, color: ttBlue),
                          const SizedBox(width: 12),
                          Expanded(
                            child: Text(
                              l['name'],
                              style: Theme.of(context).textTheme.titleMedium,
                            ),
                          ),
                        ],
                      ),
                      const SizedBox(height: 12),
                      TTBadge(
                        l['has_gateway'] == true
                            ? 'Gateway linked'
                            : 'No gateway reported',
                        color: l['has_gateway'] == true
                            ? ttBlue
                            : ttMuted(context),
                      ),
                      const SizedBox(height: 12),
                      Text('Lock ID: ${l['id']}'),
                      Text(
                        'Gateway ID: Not supplied\nGateway status: Unknown\nLast connection: Not supplied\nRemote access: Not verified',
                        style: TextStyle(color: ttMuted(context), height: 1.8),
                      ),
                    ],
                  ),
                ),
              ),
            if (!loading && locks.isEmpty && error == null)
              const TTEmpty(
                title: 'No lock connections to show',
                message:
                    'Refresh after adding a gateway in the official TTLock app.',
                icon: LucideIcons.router,
              ),
          ],
        ),
      ),
    ),
  );
}
