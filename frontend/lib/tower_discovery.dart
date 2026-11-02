import 'app_language.dart';
import 'package:flutter/material.dart';
import 'api.dart';

class TowerDiscoveryDialog extends StatefulWidget {
  final Api api;
  final bool snmp;
  final Map<String, dynamic> tower;
  const TowerDiscoveryDialog({
    super.key,
    required this.api,
    required this.tower,
    this.snmp = false,
  });

  @override
  State<TowerDiscoveryDialog> createState() => _TowerDiscoveryDialogState();
}

class _TowerDiscoveryDialogState extends State<TowerDiscoveryDialog>
    with LanguageRebuild {
  int prefix = 24;
  bool busy = false;
  String? error;
  String? summary;
  List<dynamic> hosts = [];
  List<dynamic> profiles = [];
  String? profileId;
  bool stopRequested = false;
  bool scanning = false;
  bool limited = false;
  final publicProfiles = <String, String>{};

  @override
  void initState() {
    super.initState();
    if (widget.snmp) loadProfiles();
  }

  Future<void> loadProfiles() async {
    setState(() => busy = true);
    try {
      final data = await widget.api.request('/snmp-profiles');
      if (mounted) setState(() => profiles = List<dynamic>.from(data));
    } catch (e) {
      if (mounted) setState(() => error = e.toString());
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> scanSnmp() async {
    setState(() {
      busy = true;
      error = null;
      hosts = [];
      summary = null;
      stopRequested = false;
      scanning = true;
      limited = false;
    });
    int? offset = 0;
    try {
      do {
        final result = await widget.api.request(
          '/towers/${widget.tower['id']}/discover-snmp',
          method: 'POST',
          body: {'prefix': prefix, 'offset': offset, 'profile_id': profileId},
        );
        if (!mounted) return;
        setState(() {
          hosts.addAll(result['hosts']);
          limited = limited || result['timed_out'] == true;
          summary =
              '${result['network']}: ${hosts.length} SNMP devices / ${result['scanned']} of ${result['total']} checked';
        });
        offset = result['next_offset'] as int?;
      } while (offset != null && !stopRequested);
      if (stopRequested && offset != null && mounted) {
        setState(() => summary = '$summary — stopped');
      }
    } catch (e) {
      if (mounted) setState(() => error = e.toString());
    } finally {
      if (mounted) {
        setState(() {
          busy = false;
          scanning = false;
        });
      }
    }
  }

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
        String? matchedProfile = host['snmp_profile_id'] as String?;
        if (widget.snmp && matchedProfile == null) {
          final version = host['snmp_version'].toString();
          matchedProfile = publicProfiles[version];
          if (matchedProfile == null) {
            final profile = await widget.api.request(
              '/snmp-profiles/discovery-public',
              method: 'POST',
              body: {'version': version},
            );
            matchedProfile = profile['id'];
            publicProfiles[version] = matchedProfile!;
          }
        }
        await widget.api.request(
          '/devices',
          method: 'POST',
          body: {
            'name': widget.snmp ? host['name'] : 'Device ${host['ip_address']}',
            if (widget.snmp) 'vendor': host['vendor'],
            if (widget.snmp) 'snmp_profile_id': matchedProfile,
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
        title: Text(
          '${widget.snmp ? 'Discovery SNMP' : 'Discover devices'} — ${widget.tower['name']}',
        ),
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
                AppText(
                  widget.snmp
                      ? 'Discover MikroTik, Ubiquiti M5/AC and Mimosa using SNMP. Saved v1/v2/v3 profiles and public v1/v2 are tried. SNMP v3 requires a saved profile. Ping is not required.'
                      : 'Ping the subnet containing this IP from the AirLink server. Choose the prefix that matches your network. Devices that block ping will not appear.',
                ),
                const SizedBox(height: 16),
                DropdownButtonFormField<int>(
                  initialValue: prefix,
                  decoration: InputDecoration(labelText: tr('Subnet prefix')),
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
                if (widget.snmp) ...[
                  const SizedBox(height: 12),
                  DropdownButtonFormField<String>(
                    initialValue: profileId ?? '',
                    decoration: const InputDecoration(
                      labelText: 'SNMP profile',
                    ),
                    items: [
                      const DropdownMenuItem(
                        value: '',
                        child: Text('All saved profiles + public'),
                      ),
                      for (final profile in profiles)
                        DropdownMenuItem(
                          value: profile['id'],
                          child: Text(
                            '${profile['name']} (v${profile['version'] == '2c' ? '2' : profile['version']})',
                          ),
                        ),
                    ],
                    onChanged: busy
                        ? null
                        : (value) => setState(() {
                            profileId = value == '' ? null : value;
                            hosts = [];
                            summary = null;
                            limited = false;
                            error = null;
                          }),
                  ),
                  if (limited)
                    const AppText(
                      'Some checks timed out. Select a specific profile and scan again.',
                    ),
                ],
                const SizedBox(height: 16),
                FilledButton.icon(
                  onPressed: busy
                      ? null
                      : widget.snmp
                      ? scanSnmp
                      : scan,
                  icon: const Icon(Icons.radar),
                  label: AppText(
                    widget.snmp ? 'Discover with SNMP' : 'Discover with ping',
                  ),
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
                  if (hosts.isEmpty && !busy)
                    AppText(
                      widget.snmp
                          ? 'No SNMP devices found. Check profiles, UDP 161 access and the selected subnet.'
                          : 'No ping replies. Check the subnet, routing, and ICMP firewall rules.',
                    ),
                ],
                for (final host in hosts)
                  ListTile(
                    contentPadding: EdgeInsets.zero,
                    title: Text(host['ip_address']),
                    subtitle: Text(
                      host['already_added'] == true
                          ? 'Already in inventory'
                          : widget.snmp
                          ? "${host['name']} · ${host['vendor_label']} · SNMP v${host['snmp_version'] == '2c' ? '2' : host['snmp_version']} · ${host['profile_name']}"
                          : 'Responded to ping',
                    ),
                    trailing: host['already_added'] == true
                        ? const Icon(Icons.check)
                        : TextButton(
                            onPressed: busy ? null : () => addHosts([host]),
                            child: const AppText('Add'),
                          ),
                  ),
              ],
            ),
          ),
        ),
        actions: [
          if (widget.snmp && scanning)
            TextButton(
              onPressed: () => setState(() => stopRequested = true),
              child: AppText(stopRequested ? 'Stopping…' : 'Stop discovery'),
            ),
          if (available.isNotEmpty)
            FilledButton(
              onPressed: busy ? null : () => addHosts(available),
              child: Text('Add all (${available.length})'),
            ),
          TextButton(
            onPressed: busy ? null : () => Navigator.pop(context),
            child: const AppText('Done'),
          ),
        ],
      ),
    );
  }
}
