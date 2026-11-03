import 'package:flutter/material.dart';
import 'api.dart';
import 'app_language.dart';

class SnmpVisibilityControl extends StatefulWidget {
  final Api api;
  final List<dynamic> accounts;
  final Future<void> Function() onChanged;
  const SnmpVisibilityControl({
    super.key,
    required this.api,
    required this.accounts,
    required this.onChanged,
  });
  @override
  State<SnmpVisibilityControl> createState() => _SnmpVisibilityControlState();
}

class _SnmpVisibilityControlState extends State<SnmpVisibilityControl> {
  bool busy = false;
  String? error;

  Future<void> save(bool enabled) async {
    setState(() {
      busy = true;
      error = null;
    });
    try {
      await widget.api.request(
        '/snmp-profile-visibility',
        method: 'PUT',
        body: {'enabled': enabled},
      );
      widget.api.user?['default_snmp_profile_visibility'] = enabled;
      await widget.onChanged();
    } catch (e) {
      if (mounted) {
        setState(() => error = e.toString());
      }
    } finally {
      if (mounted) {
        setState(() => busy = false);
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final accounts = widget.accounts
        .where((row) => row['role'] != 'owner')
        .toList();
    final enabled = accounts
        .where((row) => row['show_snmp_profiles'] == true)
        .length;
    final bool? selected = accounts.isEmpty
        ? (widget.api.user?['default_snmp_profile_visibility'] == true)
        : enabled == accounts.length
        ? true
        : enabled == 0
        ? false
        : null;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        CheckboxListTile(
          contentPadding: EdgeInsets.zero,
          title: const AppText('Show SNMP profiles for all managers'),
          subtitle: const AppText(
            'Applies to all non-owner accounts and new accounts. Edit an account to set its own visibility.',
          ),
          tristate: true,
          value: selected,
          onChanged: busy ? null : (value) => save(value == true),
        ),
        if (error != null)
          Text(
            error!,
            style: TextStyle(color: Theme.of(context).colorScheme.error),
          ),
      ],
    );
  }
}
