import 'package:flutter/material.dart';
import 'api.dart';

class DeyeSharing extends StatefulWidget {
  const DeyeSharing({super.key, required this.api});
  final Api api;
  @override
  State<DeyeSharing> createState() => _DeyeSharingState();
}

class _DeyeSharingState extends State<DeyeSharing> {
  List<Map<String, dynamic>> accounts = [];
  bool loading = true;
  String? saving, error;

  @override
  void initState() {
    super.initState();
    load();
  }

  Future<void> load() async {
    try {
      final rows = await widget.api.request('/integrations/deye/sharing');
      if (mounted) {
        setState(() => accounts = List<Map<String, dynamic>>.from(rows));
      }
    } catch (e) {
      if (mounted) setState(() => error = e.toString());
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }

  Future<void> share(Map<String, dynamic> account, bool enabled) async {
    setState(() {
      saving = account['id'];
      error = null;
    });
    try {
      await widget.api.request(
        '/integrations/deye/sharing/${account['id']}',
        method: 'PUT',
        body: {'enabled': enabled},
      );
      if (mounted) setState(() => account['enabled'] = enabled);
    } catch (e) {
      if (mounted) setState(() => error = e.toString());
    } finally {
      if (mounted) setState(() => saving = null);
    }
  }

  @override
  Widget build(BuildContext context) => AlertDialog(
    title: const Text('Solar visibility for Wakil / accounts'),
    content: SizedBox(
      width: 600,
      child: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text(
              'Choose who can view your solar readings. These accounts use your saved connection and cannot configure it or see your login details. Changes save immediately.',
            ),
            const SizedBox(height: 12),
            if (loading || saving != null) const LinearProgressIndicator(),
            if (!loading && accounts.isEmpty)
              const Text('No active non-owner accounts are available.'),
            for (final account in accounts)
              SwitchListTile(
                key: ValueKey('deye-share-${account['id']}'),
                contentPadding: EdgeInsets.zero,
                title: Text('${account['username']} · ${account['role_name']}'),
                subtitle: Text(
                  account['shared_by_other_owner'] == true
                      ? 'Managed by another owner'
                      : account['enabled'] == true
                      ? 'Solar readings visible · read-only'
                      : 'Solar readings hidden',
                ),
                value: account['enabled'] == true,
                onChanged:
                    loading ||
                        saving != null ||
                        account['shared_by_other_owner'] == true
                    ? null
                    : (value) => share(account, value),
              ),
            if (error != null)
              Text(
                error!,
                style: TextStyle(color: Theme.of(context).colorScheme.error),
              ),
          ],
        ),
      ),
    ),
    actions: [
      TextButton(
        onPressed: saving != null ? null : () => Navigator.pop(context),
        child: const Text('Done'),
      ),
    ],
  );
}
