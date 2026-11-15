import 'package:flutter/material.dart';
import 'api.dart';
import 'section_access.dart';

class OwnerVisibilityDialog extends StatefulWidget {
  const OwnerVisibilityDialog({
    super.key,
    required this.api,
    required this.initial,
    this.readOnly = false,
  });
  final Api api;
  final Map<String, dynamic> initial;
  final bool readOnly;

  @override
  State<OwnerVisibilityDialog> createState() => _OwnerVisibilityDialogState();
}

class _OwnerVisibilityDialogState extends State<OwnerVisibilityDialog> {
  late final selected = <String>{
    ...List<String>.from(
      widget.initial['visible_sections'] ?? ownerSections.keys.toList(),
    ),
    ...pinnedOwnerSections,
  };
  bool busy = false;
  String? error;

  Future<void> save() async {
    setState(() {
      busy = true;
      error = null;
    });
    try {
      final result = await widget.api.request(
        '/access-roles/builtin:owner/visibility',
        method: 'PUT',
        body: {
          'visible_sections': ownerSections.keys
              .where(selected.contains)
              .toList(),
        },
      );
      if (widget.api.user?['role'] == 'owner' &&
          result is Map &&
          result['visible_sections'] is List) {
        widget.api.user = {
          ...widget.api.user!,
          'visible_sections': List<String>.from(result['visible_sections']),
        };
      }
      if (mounted) Navigator.pop(context, true);
    } catch (e) {
      if (mounted) {
        setState(() {
          busy = false;
          error = '$e';
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) => AlertDialog(
    title: const Text('Owner · shown sections'),
    content: SizedBox(
      width: 540,
      child: SingleChildScrollView(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text(
              'Choose which sections appear for all owner accounts. Owner permissions stay unchanged. Access Roles and My account remain shown so you can restore hidden sections.',
            ),
            if (!widget.readOnly)
              Wrap(
                spacing: 8,
                children: [
                  TextButton(
                    onPressed: busy
                        ? null
                        : () => setState(
                            () => selected.addAll(ownerSections.keys),
                          ),
                    child: const Text('Show all'),
                  ),
                  TextButton(
                    onPressed: busy
                        ? null
                        : () => setState(() {
                            selected.clear();
                            selected.addAll(pinnedOwnerSections);
                          }),
                    child: const Text('Hide optional sections'),
                  ),
                ],
              ),
            for (final entry in ownerSections.entries)
              CheckboxListTile(
                key: ValueKey('owner-show-${entry.key}'),
                contentPadding: EdgeInsets.zero,
                controlAffinity: ListTileControlAffinity.leading,
                title: Text(entry.value),
                subtitle: Text(
                  pinnedOwnerSections.contains(entry.key)
                      ? 'Always shown'
                      : selected.contains(entry.key)
                      ? 'Shown'
                      : 'Hidden',
                ),
                value: selected.contains(entry.key),
                onChanged:
                    widget.readOnly ||
                        busy ||
                        pinnedOwnerSections.contains(entry.key)
                    ? null
                    : (value) => setState(() {
                        if (value == true) {
                          selected.add(entry.key);
                        } else {
                          selected.remove(entry.key);
                        }
                      }),
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
        onPressed: busy ? null : () => Navigator.pop(context, false),
        child: Text(widget.readOnly ? 'Close' : 'Cancel'),
      ),
      if (!widget.readOnly)
        FilledButton(
          onPressed: busy ? null : save,
          child: Text(busy ? 'Saving…' : 'Save'),
        ),
    ],
  );
}
