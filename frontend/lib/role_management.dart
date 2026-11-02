import 'dart:async';
import 'package:flutter/material.dart';
import 'api.dart';
import 'section_access.dart';

class RoleManagement extends StatefulWidget {
  final Api api;
  final bool accessGroups;
  final Future<void> Function() onChanged;
  const RoleManagement({
    super.key,
    required this.api,
    required this.accessGroups,
    required this.onChanged,
  });
  @override
  State<RoleManagement> createState() => _RoleManagementState();
}

class _RoleManagementState extends State<RoleManagement> {
  List<Map<String, dynamic>> rows = [], groups = [];
  StreamSubscription<Map<String, dynamic>>? liveSubscription;
  bool loading = true;
  String? error;
  String get endpoint => widget.accessGroups ? '/access-roles' : '/roles';
  String get section => widget.accessGroups ? 'access_roles' : 'roles';
  bool get canEdit => canEditSection(widget.api.user ?? {}, section);
  bool get canDelete => canDeleteSection(widget.api.user ?? {}, section);
  String get label => widget.accessGroups ? 'access role' : 'role';

  @override
  void initState() {
    super.initState();
    load();
    liveSubscription = widget.api.liveEvents.listen((event) {
      if (!mounted) return;
      final updated =
          event['rows']?[widget.accessGroups ? 'access-roles' : 'roles'];
      if (updated is List) {
        setState(() {
          rows = updated.map((r) => Map<String, dynamic>.from(r)).toList();
          if (widget.accessGroups) groups = rows;
        });
      } else if (event['user'] != null) {
        setState(() {});
      }
    });
  }

  @override
  void dispose() {
    liveSubscription?.cancel();
    super.dispose();
  }

  Future<void> load() async {
    try {
      final data = await widget.api.request(endpoint) as List;
      final access = widget.accessGroups
          ? data
          : await widget.api.request('/roles/access-options') as List;
      if (mounted) {
        setState(() {
          rows = data.map((r) => Map<String, dynamic>.from(r)).toList();
          groups = access.map((r) => Map<String, dynamic>.from(r)).toList();
          loading = false;
          error = null;
        });
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          error = '$e';
          loading = false;
        });
      }
    }
  }

  Future<void> edit([Map<String, dynamic>? row]) async {
    if (!canEdit || row?['can_manage'] == false) return;
    final saved = await showDialog<bool>(
      context: context,
      barrierDismissible: false,
      builder: (_) => RoleEditor(
        api: widget.api,
        accessGroup: widget.accessGroups,
        groups: groups,
        initial: row,
      ),
    );
    if (saved == true) {
      await load();
      await widget.onChanged();
    }
  }

  Future<void> view(Map<String, dynamic> row) async {
    await showDialog<void>(
      context: context,
      builder: (_) => RoleEditor(
        api: widget.api,
        accessGroup: widget.accessGroups,
        initial: row,
        readOnly: true,
        groups: widget.accessGroups
            ? groups
            : [
                {'id': row['access_role_id'], 'name': row['access_role_name']},
              ],
      ),
    );
  }

  Future<void> remove(Map<String, dynamic> row) async {
    if (!canDelete || row['can_manage'] == false) return;
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: Text('Delete $label ${row['name']}?'),
        content: const Text(
          'Reassign accounts before deleting their access role.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const Text('Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: const Text('Delete'),
          ),
        ],
      ),
    );
    if (confirmed != true) return;
    try {
      await widget.api.request('$endpoint/${row['id']}', method: 'DELETE');
      await load();
      await widget.onChanged();
    } catch (e) {
      if (mounted) setState(() => error = '$e');
    }
  }

  @override
  Widget build(BuildContext context) => Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    children: [
      Text(
        widget.accessGroups
            ? 'Manage account types and their read, edit and delete permissions. Owner always keeps full access.'
            : 'Create a role, choose its access group, then assign the role in Managers.',
      ),
      const SizedBox(height: 16),
      FilledButton.icon(
        onPressed: loading || !canEdit ? null : () => edit(),
        icon: const Icon(Icons.add),
        label: Text(widget.accessGroups ? 'Add access role' : 'Add role'),
      ),
      if (loading) const LinearProgressIndicator(),
      if (error != null)
        Padding(
          padding: const EdgeInsets.symmetric(vertical: 12),
          child: Text(
            error!,
            style: TextStyle(color: Theme.of(context).colorScheme.error),
          ),
        ),
      const SizedBox(height: 16),
      if (!loading && rows.isEmpty)
        Text('No ${widget.accessGroups ? 'access groups' : 'roles'} yet.'),
      for (final row in rows)
        Card(
          child: ListTile(
            title: Text(row['name']),
            subtitle: Text(
              row['account_type'] == 'owner'
                  ? 'Owner · full access'
                  : widget.accessGroups
                  ? '${(row['sections'] as List).length} read · ${(row['editable_sections'] as List).length} edit · ${(row['deletable_sections'] as List).length} delete'
                  : 'Access group: ${row['access_role_name']}',
            ),
            trailing: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                IconButton(
                  tooltip: 'View $label',
                  onPressed: () => view(row),
                  icon: const Icon(Icons.visibility_outlined),
                ),
                IconButton(
                  tooltip: 'Edit $label',
                  onPressed: !canEdit || row['can_manage'] == false
                      ? null
                      : () => edit(row),
                  icon: const Icon(Icons.edit_outlined),
                ),
                IconButton(
                  tooltip: 'Delete $label',
                  onPressed: !canDelete || row['can_manage'] == false
                      ? null
                      : () => remove(row),
                  icon: const Icon(Icons.delete_outline),
                ),
              ],
            ),
          ),
        ),
    ],
  );
}

class RoleEditor extends StatefulWidget {
  final Api api;
  final bool accessGroup;
  final bool readOnly;
  final List<Map<String, dynamic>> groups;
  final Map<String, dynamic>? initial;
  const RoleEditor({
    super.key,
    required this.api,
    required this.accessGroup,
    required this.groups,
    this.initial,
    this.readOnly = false,
  });
  @override
  State<RoleEditor> createState() => _RoleEditorState();
}

class _RoleEditorState extends State<RoleEditor> {
  final form = GlobalKey<FormState>();
  late final name = TextEditingController(text: widget.initial?['name'] ?? '');
  late String? group = widget.initial?['access_role_id'];
  late final read = Set<String>.from(widget.initial?['sections'] ?? []);
  late final edit = Set<String>.from(
    widget.initial?['editable_sections'] ?? [],
  );
  late final delete = Set<String>.from(
    widget.initial?['deletable_sections'] ?? [],
  );
  bool busy = false;
  String? error;
  @override
  void dispose() {
    name.dispose();
    super.dispose();
  }

  Future<void> save() async {
    if (widget.readOnly || !form.currentState!.validate()) return;
    setState(() {
      busy = true;
      error = null;
    });
    try {
      final endpoint = widget.accessGroup ? '/access-roles' : '/roles';
      await widget.api.request(
        '$endpoint${widget.initial == null ? '' : '/${widget.initial!['id']}'}',
        method: widget.initial == null ? 'POST' : 'PUT',
        body: {
          'name': name.text.trim(),
          if (!widget.accessGroup) 'access_role_id': group,
          if (widget.accessGroup) ...{
            'sections': assignableSections.keys.where(read.contains).toList(),
            'editable_sections': assignableSections.keys
                .where(edit.contains)
                .toList(),
            'deletable_sections': assignableSections.keys
                .where(delete.contains)
                .toList(),
          },
        },
      );
      if (mounted) Navigator.pop(context, true);
    } catch (e) {
      if (mounted) {
        setState(() {
          error = '$e';
          busy = false;
        });
      }
    }
  }

  Widget permission(String key, String action, Set<String> values) => Checkbox(
    key: ValueKey('$action-$key'),
    value: values.contains(key),
    onChanged:
        widget.readOnly || busy || (action != 'read' && !read.contains(key))
        ? null
        : (value) => setState(() {
            if (value == true) {
              values.add(key);
            } else {
              values.remove(key);
            }
            if (!read.contains(key)) {
              edit.remove(key);
              delete.remove(key);
            }
          }),
  );

  @override
  Widget build(BuildContext context) => AlertDialog(
    title: Text(
      '${widget.readOnly
          ? 'View'
          : widget.initial == null
          ? 'Add'
          : 'Edit'} ${widget.accessGroup ? 'access role' : 'role'}',
    ),
    content: SizedBox(
      width: 620,
      child: SingleChildScrollView(
        child: Form(
          key: form,
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              TextFormField(
                controller: name,
                enabled: !busy && !widget.readOnly,
                maxLength: 64,
                decoration: const InputDecoration(labelText: 'Name'),
                validator: (v) =>
                    v == null || v.trim().isEmpty ? 'Name is required' : null,
              ),
              if (!widget.accessGroup) ...[
                DropdownButtonFormField<String>(
                  initialValue: group,
                  isExpanded: true,
                  decoration: const InputDecoration(labelText: 'Access role'),
                  items: widget.groups
                      .map(
                        (g) => DropdownMenuItem<String>(
                          value: g['id'],
                          child: Text(g['name']),
                        ),
                      )
                      .toList(),
                  onChanged: busy || widget.readOnly
                      ? null
                      : (v) => setState(() => group = v),
                  validator: (v) => v == null ? 'Choose an access group' : null,
                ),
                if (widget.groups.isEmpty)
                  const Text('Create an access group in Access Roles first.'),
              ] else ...[
                const Text(
                  'Read shows a section. Edit allows changes and creation. Delete is separate from Edit. Permissions apply to supported actions within assigned places. Account administration and place management remain owner-only. Managers can grant only permissions they already have.',
                ),
                const SizedBox(height: 12),
                SingleChildScrollView(
                  scrollDirection: Axis.horizontal,
                  child: DataTable(
                    columnSpacing: 18,
                    columns: const [
                      DataColumn(label: Text('Section')),
                      DataColumn(label: Text('Read')),
                      DataColumn(label: Text('Edit')),
                      DataColumn(label: Text('Delete')),
                    ],
                    rows: assignableSections.entries
                        .map(
                          (s) => DataRow(
                            cells: [
                              DataCell(Text(s.value)),
                              DataCell(permission(s.key, 'read', read)),
                              DataCell(permission(s.key, 'edit', edit)),
                              DataCell(permission(s.key, 'delete', delete)),
                            ],
                          ),
                        )
                        .toList(),
                  ),
                ),
                const SizedBox(height: 8),
                const Text(
                  'Saving changes updates every account using this access role.',
                ),
              ],
              if (error != null)
                Text(
                  error!,
                  style: TextStyle(color: Theme.of(context).colorScheme.error),
                ),
            ],
          ),
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
