import 'package:flutter/material.dart';
import 'api.dart';

class TowerDiscoveryDialog extends StatefulWidget {
  final Api api;
  final Map<String, dynamic> tower;
  const TowerDiscoveryDialog({
    super.key,
    required this.api,
    required this.tower,
  });

  @override
  State<TowerDiscoveryDialog> createState() => _TowerDiscoveryDialogState();
}

class _TowerDiscoveryDialogState extends State<TowerDiscoveryDialog> {
  int prefix = 24;
  bool busy = false;
  String? error;
  String? summary;
  List<dynamic> hosts = [];

  Future<void> scan() async {
    setState(() {
      busy = true;
      error = null;
      summary = null;
      hosts = [];
    });
    try {
      final result = await widget.api.request(
        '/towers/${widget.tower['id']}/discover',
        method: 'POST',
        body: {'prefix': prefix},
      );
      if (!mounted) return;
      setState(() {
        hosts = result['hosts'];
        summary =
            '${result['network']}: ${hosts.length} responding / ${result['scanned']} checked';
      });
    } catch (e) {
      if (mounted) setState(() => error = e.toString());
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> addHosts(List<dynamic> selected) async {
    setState(() {
      busy = true;
      error = null;
    });
    try {
      for (final host in selected) {
        await widget.api.request(
          '/devices',
          method: 'POST',
          body: {
            'name': 'Device ${host['ip_address']}',
            'ip_address': host['ip_address'],
            'tower_id': widget.tower['id'],
          },
        );
        if (!mounted) return;
        setState(() => host['already_added'] = true);
      }
    } catch (e) {
      if (mounted) setState(() => error = e.toString());
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final available = hosts
        .where((host) => host['already_added'] != true)
        .toList();
    return PopScope(
      canPop: !busy,
      child: AlertDialog(
        title: Text('Discover devices — ${widget.tower['name']}'),
        content: SizedBox(
          width: 520,
          child: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  'Management IP: ${widget.tower['management_ip'] ?? 'Not set'}',
                ),
                const SizedBox(height: 12),
                const Text(
                  'Ping the subnet containing this IP from the AirLink server. Choose the prefix that matches your network. Devices that block ping will not appear.',
                ),
                const SizedBox(height: 16),
                DropdownButtonFormField<int>(
                  initialValue: prefix,
                  decoration: const InputDecoration(labelText: 'Subnet prefix'),
                  items: [
                    for (int p = 24; p <= 32; p++)
                      DropdownMenuItem(
                        value: p,
                        child: Text(
                          p == 32 ? '/32 — management IP only' : '/$p',
                        ),
                      ),
                  ],
                  onChanged: busy
                      ? null
                      : (value) => setState(() {
                          prefix = value!;
                          hosts = [];
                          summary = null;
                          error = null;
                        }),
                ),
                const SizedBox(height: 16),
                FilledButton.icon(
                  onPressed: busy ? null : scan,
                  icon: const Icon(Icons.radar),
                  label: const Text('Discover with ping'),
                ),
                if (busy) ...[
                  const SizedBox(height: 16),
                  const LinearProgressIndicator(),
                ],
                if (error != null)
                  Padding(
                    padding: const EdgeInsets.only(top: 12),
                    child: Text(
                      error!,
                      style: TextStyle(
                        color: Theme.of(context).colorScheme.error,
                      ),
                    ),
                  ),
                if (summary != null) ...[
                  const SizedBox(height: 16),
                  Text(summary!),
                  if (hosts.isEmpty)
                    const Text(
                      'No ping replies. Check the subnet, routing, and ICMP firewall rules.',
                    ),
                ],
                for (final host in hosts)
                  ListTile(
                    contentPadding: EdgeInsets.zero,
                    title: Text(host['ip_address']),
                    subtitle: Text(
                      host['already_added'] == true
                          ? 'Already in inventory'
                          : 'Responded to ping',
                    ),
                    trailing: host['already_added'] == true
                        ? const Icon(Icons.check)
                        : TextButton(
                            onPressed: busy ? null : () => addHosts([host]),
                            child: const Text('Add'),
                          ),
                  ),
              ],
            ),
          ),
        ),
        actions: [
          if (available.isNotEmpty)
            FilledButton(
              onPressed: busy ? null : () => addHosts(available),
              child: Text('Add all (${available.length})'),
            ),
          TextButton(
            onPressed: busy ? null : () => Navigator.pop(context),
            child: const Text('Done'),
          ),
        ],
      ),
    );
  }
}
