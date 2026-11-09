import 'package:flutter/material.dart';
import 'api.dart';
import 'customer_device_access.dart';
import 'app_language.dart';
import 'section_access.dart';

const deviceLoginProfilesPath = '/integrations/sas4/device-login-profiles';
const towersApiProfilesPath = '/towers-api-profiles';

class DeviceLoginProfiles extends StatefulWidget {
  final Api api;
  final bool towers;
  const DeviceLoginProfiles({
    super.key,
    required this.api,
    this.towers = false,
  });
  @override
  State<DeviceLoginProfiles> createState() => _DeviceLoginProfilesState();
}

class _DeviceLoginProfilesState extends State<DeviceLoginProfiles> {
  String get path =>
      widget.towers ? towersApiProfilesPath : deviceLoginProfilesPath;
  String get section => widget.towers ? 'towers' : 'isp_card';
  List<dynamic> profiles = [];
  bool busy = true;
  String? error;
  @override
  void initState() {
    super.initState();
    load();
  }

  Future<void> load() async {
    if (widget.api.user?['role'] != 'owner') return;
    setState(() {
      busy = true;
      error = null;
    });
    try {
      final result = await widget.api.request(path);
      if (mounted) {
        setState(() => profiles = result as List);
      }
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

  Future<void> edit([Map<String, dynamic>? profile]) async {
    if (widget.api.user?['role'] != 'owner') return;
    final saved = await showDialog<bool>(
      context: context,
      builder: (_) => DeviceLoginProfileEditor(
        api: widget.api,
        profile: profile,
        path: path,
      ),
    );
    if (saved == true && mounted) {
      await load();
    }
  }

  Future<void> remove(Map<String, dynamic> profile) async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        title: const AppText('Delete login profile?'),
        content: Text(profile['name']),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(context, false),
            child: const AppText('Cancel'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(context, true),
            child: const AppText('Delete'),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;
    setState(() => busy = true);
    try {
      await widget.api.request('$path/${profile['id']}', method: 'DELETE');
      if (mounted) {
        await load();
      }
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
  Widget build(BuildContext context) => widget.api.user?['role'] != 'owner'
      ? const SizedBox.shrink()
      : Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            AppText(
              widget.towers ? 'Towers API' : 'Device login',
              style: Theme.of(context).textTheme.headlineSmall,
            ),
            const SizedBox(height: 12),
            if (!widget.towers) CustomerDeviceAccess(api: widget.api),
            const SizedBox(height: 12),
            profilesCard(context),
          ],
        );

  Widget profilesCard(BuildContext context) => Card(
    child: Padding(
      padding: const EdgeInsets.all(20),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Wrap(
            spacing: 16,
            runSpacing: 8,
            crossAxisAlignment: WrapCrossAlignment.center,
            children: [
              AppText(
                'Saved device logins',
                style: Theme.of(context).textTheme.titleLarge,
              ),
              if (canEditSection(widget.api.user ?? {}, section))
                FilledButton.icon(
                  onPressed: busy ? null : () => edit(),
                  icon: const Icon(Icons.add),
                  label: const AppText('Add profile'),
                ),
              TextButton(
                onPressed: busy ? null : load,
                child: const AppText('Refresh'),
              ),
            ],
          ),
          const SizedBox(height: 12),
          AppText(
            widget.towers
                ? 'Save API usernames and passwords, then choose one in Towers → devices → Login device. Profiles are also available in Device login. Saved passwords cannot be read back.'
                : 'Add multiple named usernames and passwords for your devices. Choose a profile in ISP Card → Online Users → Open device. Saved passwords cannot be read back.',
          ),
          if (busy) const LinearProgressIndicator(),
          if (error != null)
            Text(
              error!,
              style: TextStyle(color: Theme.of(context).colorScheme.error),
            ),
          if (!busy && profiles.isEmpty)
            const Padding(
              padding: EdgeInsets.symmetric(vertical: 20),
              child: AppText('No device login profiles saved.'),
            ),
          for (final row in profiles)
            ListTile(
              leading: const Icon(Icons.key_outlined),
              title: Text(row['name']),
              subtitle: Text(
                '${row['username']} • ${row['protocol']} • ${row['enabled'] == true ? 'Enabled' : 'Disabled'}${row['shared'] == true ? ' • Shared with you' : ''}${(row['assigned_managers'] as List? ?? []).isEmpty ? '' : ' • Managers: ${(row['assigned_managers'] as List).map((manager) => manager['username']).join(', ')}'}',
              ),
              trailing: Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  if (row['shared'] != true &&
                      canEditSection(widget.api.user ?? {}, section))
                    IconButton(
                      tooltip: 'Edit profile',
                      onPressed: busy
                          ? null
                          : () => edit(Map<String, dynamic>.from(row)),
                      icon: const Icon(Icons.edit_outlined),
                    ),
                  if (row['shared'] != true &&
                      canDeleteSection(widget.api.user ?? {}, section))
                    IconButton(
                      tooltip: 'Delete profile',
                      onPressed: busy
                          ? null
                          : () => remove(Map<String, dynamic>.from(row)),
                      icon: const Icon(Icons.delete_outline),
                    ),
                ],
              ),
            ),
        ],
      ),
    ),
  );
}

class DeviceLoginProfileEditor extends StatefulWidget {
  final Api api;
  final Map<String, dynamic>? profile;
  final String path;
  const DeviceLoginProfileEditor({
    super.key,
    required this.api,
    this.profile,
    this.path = deviceLoginProfilesPath,
  });
  @override
  State<DeviceLoginProfileEditor> createState() =>
      _DeviceLoginProfileEditorState();
}

class _DeviceLoginProfileEditorState extends State<DeviceLoginProfileEditor> {
  final form = GlobalKey<FormState>();
  late final name = TextEditingController(text: widget.profile?['name'] ?? '');
  late final username = TextEditingController(
    text: widget.profile?['username'] ?? '',
  );
  final password = TextEditingController();
  late final port = TextEditingController(
    text: widget.profile?['port']?.toString() ?? '',
  );
  late String protocol = widget.profile?['protocol'] ?? 'both';
  late bool enabled = widget.profile?['enabled'] ?? true,
      verifyTls = widget.profile?['verify_tls'] ?? true;
  List<dynamic> managers = [];
  late final Set<String> managerIds = Set<String>.from(
    (widget.profile?['manager_ids'] as List? ?? []).map((id) => '$id'),
  );
  bool busy = false;
  String? error;

  @override
  void initState() {
    super.initState();
    if (widget.api.user?['role'] == 'owner') loadManagers();
  }

  Future<void> loadManagers() async {
    try {
      final result = await widget.api.request('${widget.path}/managers');
      if (mounted) setState(() => managers = result as List);
    } catch (e) {
      if (mounted) setState(() => error = e.toString());
    }
  }

  @override
  void dispose() {
    name.dispose();
    username.dispose();
    password.dispose();
    port.dispose();
    super.dispose();
  }

  Future<void> save() async {
    if (!form.currentState!.validate()) return;
    setState(() {
      busy = true;
      error = null;
    });
    try {
      await widget.api.request(
        '${widget.path}${widget.profile == null ? '' : '/${widget.profile!['id']}'}',
        method: widget.profile == null ? 'POST' : 'PUT',
        body: {
          'name': name.text.trim(),
          'username': username.text.trim(),
          'password': password.text.isEmpty ? null : password.text,
          'protocol': protocol,
          'port': port.text.trim().isEmpty ? null : int.parse(port.text.trim()),
          'verify_tls': verifyTls,
          'enabled': enabled,
          if (widget.api.user?['role'] == 'owner')
            'manager_ids': managerIds.toList(),
        },
      );
      if (mounted) {
        Navigator.pop(context, true);
      }
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
  Widget build(BuildContext context) => PopScope(
    canPop: !busy,
    child: AlertDialog(
      title: AppText(
        widget.profile == null
            ? 'Add device login profile'
            : 'Edit device login profile',
      ),
      content: SizedBox(
        width: 440,
        child: SingleChildScrollView(
          child: Form(
            key: form,
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                TextFormField(
                  controller: name,
                  enabled: !busy,
                  decoration: const InputDecoration(labelText: 'Profile name'),
                  maxLength: 80,
                  validator: (v) => v == null || v.trim().isEmpty
                      ? 'Enter a profile name'
                      : null,
                ),
                TextFormField(
                  controller: username,
                  enabled: !busy,
                  decoration: const InputDecoration(
                    labelText: 'Device username',
                  ),
                  maxLength: 128,
                  validator: (v) =>
                      v == null || v.trim().isEmpty ? 'Enter a username' : null,
                ),
                TextFormField(
                  controller: password,
                  enabled: !busy,
                  obscureText: true,
                  enableSuggestions: false,
                  autocorrect: false,
                  decoration: InputDecoration(
                    labelText: 'Device password',
                    helperText: widget.profile == null
                        ? null
                        : 'Leave blank to keep the saved password.',
                  ),
                  validator: (v) =>
                      (widget.profile == null ||
                              username.text.trim() !=
                                  widget.profile?['username']) &&
                          (v == null || v.isEmpty)
                      ? 'Enter the device password'
                      : null,
                ),
                const SizedBox(height: 16),
                DropdownButtonFormField<String>(
                  initialValue: protocol,
                  decoration: const InputDecoration(labelText: 'Connection'),
                  items: const [
                    DropdownMenuItem(
                      value: 'both',
                      child: Text('HTTPS + HTTP (automatic)'),
                    ),
                    DropdownMenuItem(value: 'https', child: Text('HTTPS')),
                    DropdownMenuItem(value: 'http', child: Text('HTTP')),
                  ],
                  onChanged: busy ? null : (v) => setState(() => protocol = v!),
                ),
                TextFormField(
                  controller: port,
                  enabled: !busy,
                  decoration: const InputDecoration(
                    labelText: 'Port (optional)',
                  ),
                  keyboardType: TextInputType.number,
                  validator: (v) =>
                      v == null ||
                          v.trim().isEmpty ||
                          ((int.tryParse(v.trim()) ?? 0) >= 1 &&
                              (int.tryParse(v.trim()) ?? 65536) <= 65535)
                      ? null
                      : 'Enter a port from 1 to 65535',
                ),
                SwitchListTile(
                  title: const AppText('Verify HTTPS certificate'),
                  value: verifyTls,
                  onChanged: busy ? null : (v) => setState(() => verifyTls = v),
                ),
                SwitchListTile(
                  title: const AppText('Enabled'),
                  value: enabled,
                  onChanged: busy ? null : (v) => setState(() => enabled = v),
                ),
                if (widget.api.user?['role'] == 'owner') ...[
                  const Divider(),
                  const Align(
                    alignment: AlignmentDirectional.centerStart,
                    child: AppText(
                      'Manager access',
                      style: TextStyle(fontWeight: FontWeight.bold),
                    ),
                  ),
                  const Align(
                    alignment: AlignmentDirectional.centerStart,
                    child: AppText(
                      'Selected managers can choose this login in Open device. The saved password remains hidden.',
                    ),
                  ),
                  if (managers.isEmpty)
                    const Align(
                      alignment: AlignmentDirectional.centerStart,
                      child: AppText('No active manager accounts available.'),
                    ),
                  for (final manager in managers)
                    CheckboxListTile(
                      value: managerIds.contains('${manager['id']}'),
                      title: Text('${manager['username']}'),
                      contentPadding: EdgeInsets.zero,
                      controlAffinity: ListTileControlAffinity.leading,
                      onChanged: busy
                          ? null
                          : (selected) => setState(() {
                              if (selected == true) {
                                managerIds.add('${manager['id']}');
                              } else {
                                managerIds.remove('${manager['id']}');
                              }
                            }),
                    ),
                ],
                if (error != null)
                  Text(
                    error!,
                    style: TextStyle(
                      color: Theme.of(context).colorScheme.error,
                    ),
                  ),
              ],
            ),
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
          child: AppText(busy ? 'Saving…' : 'Save profile'),
        ),
      ],
    ),
  );
}
