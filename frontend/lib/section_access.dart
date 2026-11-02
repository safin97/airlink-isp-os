import 'package:flutter/material.dart';
import 'api.dart';
import 'app_language.dart';

const operationalSections = <String, String>{
  'dashboard': 'Dashboard',
  'noc': 'NOC Screen',
  'towers': 'Towers',
  'isp_card': 'ISP Card',
  'monitoring': 'Monitoring',
  'network_map': 'Network Map',
  'alerts': 'Alerts',
  'reports': 'Reports',
};
const assignableSections = <String, String>{
  ...operationalSections,
  'software_updates': 'Software Updates',
  'settings': 'Settings',
};
const pageSections = <String, String>{
  ...assignableSections,
  'managers': 'Managers',
};

bool hasSection(Map<String, dynamic> user, String key) {
  if (user['role'] != 'manager') return true;
  if (!assignableSections.containsKey(key)) return false;
  final sections = user['sections'] as List?;
  return sections == null
      ? operationalSections.containsKey(key)
      : sections.contains(key);
}

bool canEditSection(Map<String, dynamic> user, String key) {
  if (user['role'] == 'owner') return true;
  if (user['role'] != 'manager' || !hasSection(user, key)) return false;
  final editable = user['editable_sections'] as List?;
  return editable == null || editable.contains(key);
}

bool canReadResource(Map<String, dynamic> user, String resource) {
  if (user['role'] != 'manager') return true;
  const readers = <String, List<String>>{
    'dashboard': ['dashboard', 'noc'],
    'towers': ['towers', 'noc', 'network_map', 'monitoring'],
    'places': ['towers'],
    'devices': ['towers', 'noc', 'network_map', 'monitoring'],
    'sectors': ['towers', 'network_map', 'monitoring'],
    'alerts': ['dashboard', 'noc', 'alerts'],
    'links': ['network_map'],
    'snmp-profiles': ['settings'],
  };
  return (readers[resource] ?? []).any((key) => hasSection(user, key));
}

class SectionAccessDialog extends StatefulWidget {
  final Api api;
  final Map<String, dynamic> account;
  const SectionAccessDialog({
    super.key,
    required this.api,
    required this.account,
  });
  @override
  State<SectionAccessDialog> createState() => _SectionAccessDialogState();
}

class _SectionAccessDialogState extends State<SectionAccessDialog> {
  late final Set<String> selected = Set<String>.from(
    widget.account['sections'] as List? ?? operationalSections.keys,
  );
  late final Set<String> editable = Set<String>.from(
    widget.account['editable_sections'] as List? ?? selected,
  );
  bool busy = false;
  String? error;

  Future<void> save() async {
    setState(() {
      busy = true;
      error = null;
    });
    try {
      await widget.api.request(
        '/users/${widget.account['id']}/sections',
        method: 'PUT',
        body: {
          'sections': assignableSections.keys.where(selected.contains).toList(),
          'editable_sections': assignableSections.keys
              .where((key) => selected.contains(key) && editable.contains(key))
              .toList(),
        },
      );
      if (mounted) Navigator.pop(context, true);
    } catch (e) {
      if (mounted) {
        setState(() {
          busy = false;
          error = e.toString();
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) => AlertDialog(
    title: Text('Section access · ${widget.account['username']}'),
    content: SizedBox(
      width: 520,
      child: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const AppText(
              'Show a section to allow reading. Enable Allow edits to permit changes.',
            ),
            Row(
              children: [
                TextButton(
                  onPressed: busy
                      ? null
                      : () => setState(
                          () => selected.addAll(assignableSections.keys),
                        ),
                  child: const AppText('Select all'),
                ),
                TextButton(
                  onPressed: busy
                      ? null
                      : () => setState(() {
                          selected.clear();
                          editable.clear();
                        }),
                  child: const AppText('Clear all'),
                ),
              ],
            ),
            for (final section in assignableSections.entries)
              CheckboxListTile(
                dense: true,
                contentPadding: EdgeInsets.zero,
                controlAffinity: ListTileControlAffinity.leading,
                title: AppText(section.value),
                subtitle: AppText(
                  !selected.contains(section.key)
                      ? 'Hidden'
                      : editable.contains(section.key)
                      ? 'Can edit'
                      : 'Read-only',
                ),
                secondary: Tooltip(
                  message: 'Allow edits: ${section.value}',
                  child: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      const AppText('Allow edits'),
                      Checkbox(
                        key: ValueKey('edit-${section.key}'),
                        value:
                            selected.contains(section.key) &&
                            editable.contains(section.key),
                        onChanged: busy || !selected.contains(section.key)
                            ? null
                            : (value) => setState(() {
                                if (value == true) {
                                  editable.add(section.key);
                                } else {
                                  editable.remove(section.key);
                                }
                              }),
                      ),
                    ],
                  ),
                ),
                value: selected.contains(section.key),
                onChanged: busy
                    ? null
                    : (value) => setState(() {
                        if (value == true) {
                          selected.add(section.key);
                        } else {
                          selected.remove(section.key);
                          editable.remove(section.key);
                        }
                      }),
              ),
            const SizedBox(height: 8),
            const AppText(
              'Managers and permission controls remain owner-only. My account remains available.',
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
        onPressed: busy ? null : () => Navigator.pop(context),
        child: const AppText('Cancel'),
      ),
      FilledButton(
        onPressed: busy ? null : save,
        child: AppText(busy ? 'Saving…' : 'Save access'),
      ),
    ],
  );
}
