import 'app_language.dart';
import 'package:flutter/material.dart';
import 'api.dart';
import 'sas4_recharge.dart';
import 'section_access.dart';

class Sas4UserDetails extends StatefulWidget {
  final Api api;
  final int userId;
  const Sas4UserDetails({super.key, required this.api, required this.userId});
  @override
  State<Sas4UserDetails> createState() => _Sas4UserDetailsState();
}

class _Sas4UserDetailsState extends State<Sas4UserDetails>
    with LanguageRebuild {
  bool get canEdit => canEditSection(widget.api.user ?? {}, 'isp_card');
  final form = GlobalKey<FormState>();
  final controllers = <String, TextEditingController>{};
  final values = <String, dynamic>{};
  Map<String, dynamic>? details;
  String? error;
  bool loading = true;
  bool saving = false;
  bool editing = false;
  bool changed = false;
  bool saved = false;

  @override
  void initState() {
    super.initState();
    load();
  }

  @override
  void dispose() {
    for (final controller in controllers.values) {
      controller.dispose();
    }
    super.dispose();
  }

  dynamic fieldValue(dynamic field) {
    final key = field['key'] as String;
    final kind = field['kind'];
    if (kind == 'select' || kind == 'switch') return values[key];
    final text = controllers[key]!.text;
    return kind == 'number'
        ? int.tryParse(text)
        : text.isEmpty
        ? null
        : text;
  }

  bool fieldChanged(dynamic field) {
    if (field['editable'] != true) return false;
    final value = fieldValue(field);
    if (field['kind'] == 'password' && (value == null || value == '')) {
      return false;
    }
    return value != field['value'] && !(value == null && field['value'] == '');
  }

  Future<void> load({bool preserveEdits = false}) async {
    final editedKeys = <String>{
      if (preserveEdits && details != null)
        for (final field in details!['fields'])
          if (fieldChanged(field)) field['key'] as String,
    };
    try {
      final data = Map<String, dynamic>.from(
        await widget.api.request('/integrations/sas4/users/${widget.userId}'),
      );
      if (!mounted) return;
      for (final field in data['fields']) {
        final key = field['key'] as String;
        if (editedKeys.contains(key)) continue;
        values[key] = field['value'];
        controllers.putIfAbsent(key, () => TextEditingController()).text =
            field['value']?.toString() ?? '';
      }
      setState(() => details = data);
    } catch (e) {
      if (mounted) setState(() => error = e.toString());
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }

  Future<void> close() async {
    if (saving) return;
    if (mounted) Navigator.pop(context, saved);
  }

  Future<bool> save() async {
    if (!canEdit) return false;
    if (!form.currentState!.validate()) return false;
    final changes = <String, dynamic>{};
    for (final field in details!['fields']) {
      if (fieldChanged(field)) changes[field['key']] = fieldValue(field);
    }
    if (changes.isEmpty) {
      setState(() {
        changed = false;
        editing = false;
      });
      return true;
    }
    setState(() {
      saving = true;
      error = null;
    });
    try {
      await widget.api.request(
        '/integrations/sas4/users/${widget.userId}',
        method: 'PUT',
        body: {'changes': changes},
      );
      if (!mounted) return false;
      setState(() {
        for (final field in details!['fields']) {
          final key = field['key'] as String;
          if (field['kind'] == 'password') {
            controllers[key]!.clear();
          } else if (changes.containsKey(key)) {
            field['value'] = changes[key];
          }
        }
        if (changes.containsKey('username')) {
          details!['username'] = changes['username'];
        }
        changed = false;
        editing = false;
        saved = true;
      });
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: AppText('User information saved to SAS4.')),
      );
      return true;
    } catch (e) {
      if (mounted) setState(() => error = e.toString());
      return false;
    } finally {
      if (mounted) setState(() => saving = false);
    }
  }

  Future<void> rechargeCard() async {
    if (!canEdit) return;
    if (saving) return;
    setState(() => saving = true);
    final recharged = await showDialog<bool>(
      context: context,
      barrierDismissible: false,
      builder: (_) => Sas4Recharge(
        api: widget.api,
        userId: widget.userId,
        hasUnsavedEdits: changed,
      ),
    );
    if (!mounted) return;
    if (recharged == true) {
      saved = true;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: AppText('Card recharged successfully.')),
      );
      await load(preserveEdits: true);
    }
    if (mounted) setState(() => saving = false);
  }

  Widget rechargeSquare() {
    final allowed = details?['can_recharge'] == true;
    final enabled = canEdit && allowed && !saving;
    return SizedBox(
      width: 160,
      height: 160,
      child: Card(
        margin: EdgeInsets.zero,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(14),
          side: BorderSide(
            color: Theme.of(context).colorScheme.primary.withValues(alpha: .4),
          ),
        ),
        child: InkWell(
          onTap: enabled ? rechargeCard : null,
          borderRadius: BorderRadius.circular(14),
          child: Padding(
            padding: const EdgeInsets.all(12),
            child: Column(
              mainAxisAlignment: MainAxisAlignment.center,
              children: [
                Icon(
                  Icons.add_card,
                  size: 32,
                  color: enabled
                      ? Theme.of(context).colorScheme.primary
                      : Colors.grey,
                ),
                const SizedBox(height: 8),
                const FittedBox(
                  fit: BoxFit.scaleDown,
                  child: AppText(
                    'Recharge card',
                    style: TextStyle(fontWeight: FontWeight.w600, fontSize: 14),
                  ),
                ),
                const SizedBox(height: 8),
                AppText(
                  !canEdit
                      ? 'Read-only access'
                      : !allowed
                      ? 'SAS4 permission required'
                      : changed
                      ? 'Your edits stay unsaved'
                      : 'Choose recharge type',
                  textAlign: TextAlign.center,
                  style: const TextStyle(fontSize: 11, height: 1.2),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  Widget fieldWidget(Map<String, dynamic> field) {
    final key = field['key'] as String;
    final kind = field['kind'];
    final editable = canEdit && field['editable'] == true;
    final label = field['label'] as String;
    final help = !editable
        ? field['reason'] as String?
        : kind == 'password'
        ? 'Leave blank to keep the current password'
        : kind == 'datetime'
        ? 'YYYY-MM-DD HH:MM:SS • SAS4 server time'
        : field['help'] as String?;
    final decoration = InputDecoration(
      labelText: tr(label),
      helperText: help == null ? null : tr(help),
      helperMaxLines: 3,
      border: const OutlineInputBorder(),
    );
    if (kind == 'switch') {
      return SwitchListTile(
        contentPadding: EdgeInsets.zero,
        title: AppText(label),
        subtitle: help == null ? null : AppText(help),
        value: values[key] == 1 || values[key] == true,
        onChanged: editable && editing && !saving
            ? (value) => setState(() {
                values[key] = value ? 1 : 0;
                changed = true;
              })
            : null,
      );
    }
    if (kind == 'select') {
      final options = field['options'] as List;
      // String encoding keeps the None option selectable in Flutter dropdowns.
      return DropdownButtonFormField<String>(
        initialValue: '${values[key]}',
        isExpanded: true,
        decoration: decoration,
        items: options
            .map(
              (option) => DropdownMenuItem(
                value: '${option['value']}',
                child: Text(
                  '${option['label']}',
                  overflow: TextOverflow.ellipsis,
                ),
              ),
            )
            .toList(),
        onChanged: editable && editing && !saving
            ? (value) {
                setState(() {
                  values[key] = value == 'null' ? null : int.parse(value!);
                  changed = true;
                });
              }
            : null,
      );
    }
    return TextFormField(
      controller: controllers[key],
      readOnly: !editable || !editing || saving,
      obscureText: kind == 'password',
      enableSuggestions: kind != 'password',
      autocorrect: kind != 'password',
      maxLines: kind == 'multiline' ? 3 : 1,
      decoration: decoration,
      keyboardType: kind == 'number'
          ? TextInputType.number
          : key == 'phone'
          ? TextInputType.phone
          : TextInputType.text,
      onChanged: (_) => setState(() => changed = true),
      validator: (value) {
        if (!editable) return null;
        if (key == 'username' &&
            (value == null ||
                !RegExp(r'^[a-zA-Z.@_0-9:\-]+$').hasMatch(value))) {
          return 'Enter a valid username';
        }
        if (kind == 'number' && (int.tryParse(value ?? '') ?? 0) < 1) {
          return 'Enter a positive number';
        }
        if (kind == 'datetime' &&
            value != null &&
            value.isNotEmpty &&
            !RegExp(r'^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$').hasMatch(value)) {
          return 'Use YYYY-MM-DD HH:MM:SS';
        }
        return null;
      },
    );
  }

  @override
  Widget build(BuildContext context) => PopScope(
    canPop: !saving,
    onPopInvokedWithResult: (didPop, result) {
      if (!didPop) close();
    },
    child: Scaffold(
      appBar: AppBar(
        leading: IconButton(
          onPressed: saving ? null : close,
          icon: const Icon(Icons.arrow_back),
        ),
        title: Text(
          details == null
              ? tr('User information')
              : "${details!['username']} • ${tr('User information')}",
        ),
        actions: [
          Padding(
            padding: const EdgeInsets.only(right: 16),
            child: FilledButton.icon(
              onPressed:
                  !canEdit ||
                      loading ||
                      saving ||
                      details == null ||
                      (editing && !changed) ||
                      !(details!['fields'] as List).any(
                        (field) => field['editable'] == true,
                      )
                  ? null
                  : editing
                  ? save
                  : () => setState(() => editing = true),
              icon: Icon(editing ? Icons.save_outlined : Icons.edit_outlined),
              label: AppText(
                saving
                    ? 'Saving…'
                    : editing
                    ? 'Save changes'
                    : 'Edit',
              ),
            ),
          ),
        ],
      ),
      body: loading
          ? const Center(child: CircularProgressIndicator())
          : SingleChildScrollView(
              padding: const EdgeInsets.all(24),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  if (error != null)
                    Padding(
                      padding: const EdgeInsets.only(bottom: 20),
                      child: Text(
                        error!,
                        style: TextStyle(
                          color: Theme.of(context).colorScheme.error,
                        ),
                      ),
                    ),
                  if (details != null) ...[
                    rechargeSquare(),
                    const SizedBox(height: 20),
                    AppText(
                      editing
                          ? 'Changes are saved to SAS4 when you select Save changes.'
                          : 'Select Edit to change user information.',
                    ),
                    const SizedBox(height: 20),
                    Form(
                      key: form,
                      child: LayoutBuilder(
                        builder: (context, constraints) {
                          final width = constraints.maxWidth >= 700
                              ? (constraints.maxWidth - 20) / 2
                              : constraints.maxWidth;
                          return Wrap(
                            spacing: 20,
                            runSpacing: 20,
                            children: [
                              for (final field in details!['fields'])
                                SizedBox(
                                  width: width,
                                  child: fieldWidget(
                                    Map<String, dynamic>.from(field),
                                  ),
                                ),
                            ],
                          );
                        },
                      ),
                    ),
                  ],
                ],
              ),
            ),
    ),
  );
}
