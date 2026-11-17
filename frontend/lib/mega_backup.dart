import 'dart:async';
import 'package:flutter/material.dart';
import 'api.dart';
import 'mega_restore.dart';

class MegaBackup extends StatefulWidget {
  const MegaBackup({super.key, required this.api});
  final Api api;
  @override
  State<MegaBackup> createState() => _MegaBackupState();
}

class _MegaBackupState extends State<MegaBackup> {
  static const path = '/backups/mega';
  final form = GlobalKey<FormState>();
  final email = TextEditingController(),
      accountPassword = TextEditingController(),
      backupPassword = TextEditingController(),
      confirm = TextEditingController(),
      folder = TextEditingController(text: 'AirLink Backups'),
      clock = TextEditingController(text: '02:00'),
      zone = TextEditingController(text: 'Europe/Zurich');
  Map<String, dynamic> data = {};
  bool loading = true,
      busy = false,
      fetching = false,
      dirty = false,
      automatic = true;
  int weekday = 6, generation = 0;
  String? error, message;
  Timer? timer;
  bool get owner => widget.api.user?['role'] == 'owner';
  bool get running =>
      data['running'] == true ||
      data['testing'] == true ||
      ['uploading', 'awaiting_restart'].contains(data['restore']?['status']);
  Map get state => data['state'] as Map? ?? {};

  @override
  void initState() {
    super.initState();
    if (owner) {
      load(initial: true);
      timer = Timer.periodic(const Duration(seconds: 5), (_) => load());
    }
  }

  @override
  void dispose() {
    timer?.cancel();
    for (final control in [
      email,
      accountPassword,
      backupPassword,
      confirm,
      folder,
      clock,
      zone,
    ]) {
      control.dispose();
    }
    super.dispose();
  }

  void apply(Map<String, dynamic> next, {bool fields = false}) {
    data = next;
    if (fields) {
      email.text = next['email'] ?? '';
      folder.text = next['folder'] ?? 'AirLink Backups';
      clock.text = next['time'] ?? '02:00';
      zone.text = next['timezone'] ?? 'Europe/Zurich';
      weekday = next['weekday'] as int? ?? 6;
      automatic = email.text.isEmpty || next['automatic_enabled'] == true;
      dirty = false;
    }
  }

  Future<void> load({bool initial = false}) async {
    if (!owner || busy || fetching) return;
    fetching = true;
    final current = generation;
    try {
      final next = Map<String, dynamic>.from(await widget.api.request(path));
      if (mounted && current == generation) {
        setState(() => apply(next, fields: initial && !dirty));
      }
    } catch (e) {
      if (mounted && current == generation) {
        setState(() => error = e.toString());
      }
    } finally {
      fetching = false;
      if (mounted) setState(() => loading = false);
    }
  }

  Future<void> action(String suffix, {Object? body}) async {
    generation++;
    setState(() {
      busy = true;
      error = null;
      message = null;
    });
    try {
      final next = Map<String, dynamic>.from(
        await widget.api.request(
          '$path$suffix',
          method: suffix.isEmpty ? 'PUT' : 'POST',
          body: body,
        ),
      );
      if (!mounted) return;
      setState(() {
        apply(next, fields: suffix.isEmpty || suffix == '/disconnect');
        if (suffix.isEmpty) {
          accountPassword.clear();
          backupPassword.clear();
          confirm.clear();
        }
        message = switch (suffix) {
          '/test' =>
            'MEGA connection verified. Weekly backups follow your saved schedule.',
          '/run' =>
            'MEGA backup started. You can close this page; the server continues working.',
          '/disconnect' =>
            'MEGA disconnected and weekly backups stopped. Existing cloud backups are kept.',
          _ =>
            'MEGA settings saved. Test the connection before your first backup.',
        };
      });
    } catch (e) {
      if (mounted) setState(() => error = e.toString());
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  void save() {
    if (!form.currentState!.validate()) return;
    action(
      '',
      body: {
        'email': email.text.trim(),
        'folder': folder.text.trim(),
        'account_password': accountPassword.text.isEmpty
            ? null
            : accountPassword.text,
        'backup_password': backupPassword.text.isEmpty
            ? null
            : backupPassword.text,
        'automatic_enabled': automatic,
        'weekday': weekday,
        'time': clock.text.trim(),
        'timezone': zone.text.trim(),
      },
    );
  }

  Widget field(
    String label,
    TextEditingController control, {
    bool secret = false,
    String? help,
    String? Function(String?)? validate,
  }) => Padding(
    padding: const EdgeInsets.only(bottom: 12),
    child: TextFormField(
      controller: control,
      obscureText: secret,
      autocorrect: false,
      enableSuggestions: !secret,
      enabled: !busy && !running,
      onChanged: (_) => setState(() => dirty = true),
      decoration: InputDecoration(
        labelText: label,
        helperText: help,
        helperMaxLines: 3,
      ),
      validator:
          validate ??
          (value) => (value?.trim().isEmpty ?? true) ? 'Required' : null,
    ),
  );

  String date(dynamic value) {
    final parsed = value is String ? DateTime.tryParse(value) : null;
    return parsed == null ? 'Not scheduled' : '${parsed.toLocal()}';
  }

  @override
  Widget build(BuildContext context) {
    if (!owner) return const SizedBox.shrink();
    final disabled = busy || loading || running;
    const days = [
      'Monday',
      'Tuesday',
      'Wednesday',
      'Thursday',
      'Friday',
      'Saturday',
      'Sunday',
    ];
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(
              'MEGA cloud backup',
              style: Theme.of(context).textTheme.titleLarge,
            ),
            const SizedBox(height: 8),
            const Text(
              'Upload encrypted backups to your MEGA account, on demand or every week. No domain or callback URL is needed.',
            ),
            const SizedBox(height: 8),
            Text(
              data['connected'] == true
                  ? 'MEGA connection verified: ${data['email']}'
                  : 'MEGA is not connected',
            ),
            Text('MEGA status: ${state['status'] ?? 'Ready'}'),
            Text(
              'Last successful MEGA backup: ${state['last_success_at'] == null ? 'None yet' : date(state['last_success_at'])}',
            ),
            Text('Next MEGA backup: ${date(state['next_run_at'])}'),
            if (data['restore']?['status'] != null) ...[
              Text('Backup recovery: ${data['restore']['status']}'),
              if (data['restore']['message'] != null)
                SelectableText(data['restore']['message']),
              if (data['restore']['error'] != null)
                Text(data['restore']['error']),
            ],
            if (data['local_mode'] == true)
              const Text(
                'Local mode backs up this Mac’s database and recovery key. Keep the Mac awake and the live server running for weekly uploads.',
              ),
            if (data['transfer_available'] == false)
              const Text(
                'MEGA transfer support is not installed on this server. Follow the MEGA backup setup instructions.',
              ),
            if (data['supported'] == false &&
                data['transfer_available'] == true)
              const Text(
                'Start the live server to enable MEGA backup uploads and the weekly scheduler.',
              ),
            if (loading || busy || running) const LinearProgressIndicator(),
            if (error != null ||
                state['error'] != null ||
                state['connection_error'] != null)
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 8),
                child: Text(
                  error ?? state['error'] ?? state['connection_error'],
                  style: TextStyle(color: Theme.of(context).colorScheme.error),
                ),
              ),
            if (message != null)
              Padding(
                padding: const EdgeInsets.symmetric(vertical: 8),
                child: Text(message!),
              ),
            const SizedBox(height: 12),
            Wrap(
              spacing: 12,
              runSpacing: 12,
              children: [
                OutlinedButton(
                  onPressed:
                      disabled ||
                          dirty ||
                          data['has_account_password'] != true ||
                          data['transfer_available'] != true
                      ? null
                      : () => action('/test'),
                  child: const Text('Test MEGA connection'),
                ),
                FilledButton.icon(
                  onPressed:
                      disabled ||
                          dirty ||
                          data['connected'] != true ||
                          data['supported'] != true
                      ? null
                      : () => action('/run'),
                  icon: const Icon(Icons.cloud_upload_outlined),
                  label: const Text('Back up to MEGA now'),
                ),
                TextButton(
                  onPressed:
                      busy || loading || dirty || data['connected'] != true
                      ? null
                      : () async {
                          await showDialog<void>(
                            context: context,
                            builder: (_) => MegaRestoreDialog(api: widget.api),
                          );
                          await load();
                        },
                  child: const Text('Restore from MEGA'),
                ),
                TextButton(
                  onPressed: disabled || data['has_account_password'] != true
                      ? null
                      : () => action('/disconnect'),
                  child: const Text('Disconnect MEGA'),
                ),
              ],
            ),
            ExpansionTile(
              title: const Text('MEGA account and weekly schedule'),
              initiallyExpanded: false,
              children: [
                Form(
                  key: form,
                  child: Column(
                    children: [
                      const Padding(
                        padding: EdgeInsets.only(bottom: 12),
                        child: Text(
                          'Sign in to your MEGA account in its website at least once before setup. '
                          'This integration requires unattended email/password login; accounts requiring a one-time sign-in code are not supported.',
                        ),
                      ),
                      field('MEGA email', email),
                      field(
                        'MEGA account password',
                        accountPassword,
                        secret: true,
                        help: data['has_account_password'] == true
                            ? 'Leave blank to keep the saved account password.'
                            : null,
                        validate: (value) =>
                            (value?.isEmpty ?? true) &&
                                data['has_account_password'] != true
                            ? 'Required'
                            : null,
                      ),
                      field('MEGA backup folder', folder),
                      field(
                        'MEGA backup encryption password',
                        backupPassword,
                        secret: true,
                        help:
                            'Keep this password outside AirLink; it is required for recovery. Leave blank to keep a saved password.',
                        validate: (value) =>
                            (value?.isEmpty ?? true) &&
                                data['has_backup_password'] == true
                            ? null
                            : (value?.length ?? 0) < 12
                            ? 'Use at least 12 characters'
                            : null,
                      ),
                      field(
                        'Confirm MEGA backup password',
                        confirm,
                        secret: true,
                        validate: (value) => value != backupPassword.text
                            ? 'Passwords do not match'
                            : null,
                      ),
                      SwitchListTile(
                        title: const Text('Weekly automatic MEGA backup'),
                        value: automatic,
                        onChanged: disabled
                            ? null
                            : (value) => setState(() {
                                automatic = value;
                                dirty = true;
                              }),
                      ),
                      DropdownButtonFormField<int>(
                        initialValue: weekday,
                        key: ValueKey('mega-day-$weekday'),
                        decoration: const InputDecoration(
                          labelText: 'MEGA backup day',
                        ),
                        items: [
                          for (var i = 0; i < days.length; i++)
                            DropdownMenuItem(value: i, child: Text(days[i])),
                        ],
                        onChanged: disabled
                            ? null
                            : (value) => setState(() {
                                weekday = value!;
                                dirty = true;
                              }),
                      ),
                      const SizedBox(height: 12),
                      field(
                        'MEGA backup time (HH:MM)',
                        clock,
                        validate: (value) =>
                            RegExp(
                              r'^(?:[01][0-9]|2[0-3]):[0-5][0-9]$',
                            ).hasMatch(value ?? '')
                            ? null
                            : 'Use HH:MM',
                      ),
                      field(
                        'MEGA backup timezone',
                        zone,
                        help: 'For example Europe/Zurich or Asia/Baghdad.',
                      ),
                      const Text(
                        'Uploads continue while you are signed out. Existing backups stay in MEGA until you delete them. Verification reads the uploaded file back and uses transfer quota.',
                      ),
                      const SizedBox(height: 12),
                      FilledButton(
                        onPressed: disabled ? null : save,
                        child: const Text('Save MEGA settings'),
                      ),
                    ],
                  ),
                ),
              ],
            ),
            if (state['last_backup'] is Map) ...[
              const SizedBox(height: 8),
              Text(
                'Last verified file: ${state['last_backup']['remote_path']}',
              ),
            ],
            if ((state['history'] as List? ?? []).isNotEmpty)
              ExpansionTile(
                title: const Text('Recent MEGA backups'),
                children: [
                  for (final entry in (state['history'] as List).take(20))
                    ListTile(
                      title: Text(
                        '${entry['status']} — ${date(entry['finished_at'])}',
                      ),
                      subtitle: Text(
                        entry['error'] ?? entry['backup']?['filename'] ?? '',
                      ),
                    ),
                ],
              ),
          ],
        ),
      ),
    );
  }
}
