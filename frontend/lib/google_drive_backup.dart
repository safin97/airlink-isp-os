import 'dart:async';
import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';
import 'api.dart';
import 'app_language.dart';
import 'drive_oauth.dart';

class GoogleDriveBackup extends StatefulWidget {
  const GoogleDriveBackup({super.key, required this.api});
  final Api api;
  @override
  State<GoogleDriveBackup> createState() => _GoogleDriveBackupState();
}

class _GoogleDriveBackupState extends State<GoogleDriveBackup> {
  static const path = '/backups/google-drive';
  final form = GlobalKey<FormState>();
  final clientId = TextEditingController(),
      clientSecret = TextEditingController(),
      callback = TextEditingController(),
      folder = TextEditingController(text: 'AirLink Backups'),
      password = TextEditingController(),
      confirm = TextEditingController(),
      clock = TextEditingController(text: '02:00'),
      zone = TextEditingController(text: 'UTC');
  Map<String, dynamic> data = {};
  bool automatic = true, busy = false, loading = true, dirty = false;
  bool fetching = false;
  int generation = 0;
  int weekday = 6;
  String? error, message;
  Timer? timer;
  DriveOAuth? oauth;
  bool get owner => widget.api.user?['role'] == 'owner';
  bool get running => data['running'] == true;
  Map get status => data['state'] as Map? ?? {};

  @override
  void initState() {
    super.initState();
    final origin = ['https', 'http'].contains(Uri.base.scheme)
        ? Uri.base.origin
        : 'http://localhost';
    callback.text = '$origin/api/backups/google-drive/callback';
    if (owner) {
      load(initial: true);
      timer = Timer.periodic(const Duration(seconds: 5), (_) {
        if (!busy) load();
      });
    }
  }

  @override
  void dispose() {
    timer?.cancel();
    oauth?.close();
    for (final control in [
      clientId,
      clientSecret,
      callback,
      folder,
      password,
      confirm,
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
      clientId.text = next['client_id'] ?? '';
      if ('${next['redirect_uri'] ?? ''}'.isNotEmpty) {
        callback.text = next['redirect_uri'];
      }
      folder.text = next['folder_name'] ?? 'AirLink Backups';
      clock.text = next['time'] ?? '02:00';
      zone.text = next['timezone'] ?? 'UTC';
      automatic = clientId.text.isEmpty || next['automatic_enabled'] == true;
      weekday = next['weekday'] as int? ?? 6;
      dirty = false;
    }
  }

  Future<void> load({bool initial = false}) async {
    if (!owner || fetching || busy) return;
    fetching = true;
    final current = generation;
    try {
      final next = Map<String, dynamic>.from(await widget.api.request(path));
      if (mounted && current == generation) {
        setState(() {
          apply(next, fields: initial);
        });
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

  Future<void> action(
    String suffix, {
    String method = 'POST',
    Map<String, dynamic>? body,
  }) async {
    if (!owner || busy) return;
    generation++;
    setState(() {
      busy = true;
      error = null;
      message = null;
    });
    try {
      final next = Map<String, dynamic>.from(
        await widget.api.request(path + suffix, method: method, body: body),
      );
      if (mounted) {
        setState(() {
          apply(next, fields: method == 'PUT' || suffix == '/disconnect');
          if (method == 'PUT') {
            clientSecret.clear();
            password.clear();
            confirm.clear();
          }
          message =
              next['notice'] ??
              (suffix == '/run'
                  ? 'Backup started. You can close this page; progress continues on the server.'
                  : suffix == '/disconnect'
                  ? 'Google Drive disconnected. Existing backups are kept.'
                  : 'Backup settings saved.');
        });
      }
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
      method: 'PUT',
      body: {
        'client_id': clientId.text.trim(),
        'client_secret': clientSecret.text.isEmpty ? null : clientSecret.text,
        'redirect_uri': callback.text.trim(),
        'folder_name': folder.text.trim(),
        'backup_password': password.text.isEmpty ? null : password.text,
        'automatic_enabled': automatic,
        'weekday': weekday,
        'time': clock.text.trim(),
        'timezone': zone.text.trim(),
      },
    );
  }

  Future<void> connect() async {
    if (!owner || busy) return;
    generation++;
    oauth =
        DriveOAuth(); // Open synchronously during the click so browsers can allow the popup.
    setState(() {
      busy = true;
      message = null;
      error = null;
    });
    try {
      final start = await widget.api.request('$path/authorize', method: 'POST');
      final result = await oauth!.authorize(
        start['authorization_url'],
        start['state'],
      );
      if (result['error'] != null || result['code'] == null) {
        throw Exception(
          'Google sign-in was not completed. Connect again to retry.',
        );
      }
      final next = await widget.api.request(
        '$path/complete',
        method: 'POST',
        body: {'code': result['code'], 'state': result['state']},
      );
      if (mounted) {
        setState(() {
          apply(Map<String, dynamic>.from(next));
          message = 'Google Drive connected.';
        });
      }
    } catch (e) {
      if (mounted) setState(() => error = e.toString());
    } finally {
      oauth?.close();
      oauth = null;
      if (mounted) setState(() => busy = false);
    }
  }

  String date(dynamic value) => value == null
      ? 'Not yet'
      : DateTime.tryParse('$value')?.toLocal().toString().split('.').first ??
            '$value';

  Future<void> openLink(String value) async {
    final uri = Uri.parse(value);
    if (uri.scheme == 'https' &&
        [
          'drive.google.com',
          'console.cloud.google.com',
          'developers.google.com',
        ].contains(uri.host)) {
      await launchUrl(uri, mode: LaunchMode.externalApplication);
    }
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
      enableSuggestions: !secret,
      autocorrect: false,
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

  @override
  Widget build(BuildContext context) {
    if (!owner) return const SizedBox.shrink();
    const days = [
      'Monday',
      'Tuesday',
      'Wednesday',
      'Thursday',
      'Friday',
      'Saturday',
      'Sunday',
    ];
    final last = status['last_backup'] as Map?;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        const AppText(
          'Back up the AirLink database and configuration to your Google Drive. Uploads are encrypted with your backup password.',
        ),
        if (loading || busy) const LinearProgressIndicator(),
        if (error != null)
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 12),
            child: Text(
              error!,
              style: TextStyle(color: Theme.of(context).colorScheme.error),
            ),
          ),
        if (message != null)
          Padding(
            padding: const EdgeInsets.symmetric(vertical: 12),
            child: Text(message!),
          ),
        if (data['supported'] == false)
          const Padding(
            padding: EdgeInsets.symmetric(vertical: 12),
            child: AppText(
              'Backup creation and automatic schedules run on the installed AirLink appliance. They are unavailable in the local preview.',
            ),
          ),
        Card(
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  data['connected'] == true
                      ? 'Connected: ${data['account_email']}'
                      : 'Google Drive is not connected',
                  style: Theme.of(context).textTheme.titleMedium,
                ),
                Text(
                  'Last successful backup: ${date(status['last_success_at'])}',
                ),
                Text(
                  'Next weekly backup: ${data['connected'] == true && data['automatic_enabled'] == true ? date(status['next_run_at']) : 'Not scheduled'}',
                ),
                Text('Backup status: ${status['status'] ?? 'Ready'}'),
                if (running) ...[
                  const SizedBox(height: 8),
                  LinearProgressIndicator(
                    value:
                        status['total_bytes'] is num &&
                            status['total_bytes'] > 0
                        ? (status['uploaded_bytes'] as num? ?? 0) /
                              status['total_bytes']
                        : null,
                  ),
                ],
                if (status['error'] != null)
                  Text(
                    '${status['error']}',
                    style: TextStyle(
                      color: Theme.of(context).colorScheme.error,
                    ),
                  ),
                Wrap(
                  spacing: 12,
                  runSpacing: 8,
                  children: [
                    FilledButton.icon(
                      onPressed:
                          !busy &&
                              !running &&
                              data['connected'] == true &&
                              data['supported'] == true
                          ? () => action('/run')
                          : null,
                      icon: const Icon(Icons.backup_outlined),
                      label: const AppText('Back up now'),
                    ),
                    if (data['folder_url'] != null)
                      TextButton(
                        onPressed: () => openLink(data['folder_url']),
                        child: const AppText('Open backup folder'),
                      ),
                    if (last?['file_url'] != null)
                      TextButton(
                        onPressed: () => openLink(last!['file_url']),
                        child: const AppText('View last backup in Drive'),
                      ),
                  ],
                ),
              ],
            ),
          ),
        ),
        Card(
          child: Padding(
            padding: const EdgeInsets.all(16),
            child: Form(
              key: form,
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Text(
                    'Google Drive connection',
                    style: Theme.of(context).textTheme.titleMedium,
                  ),
                  const SizedBox(height: 8),
                  const AppText(
                    'Enable Google Drive API in Google Cloud, create a Web application OAuth client and register the callback URL below. Use an HTTPS domain for AirLink; Google does not accept a public IP address as the callback.',
                  ),
                  Align(
                    alignment: Alignment.centerLeft,
                    child: TextButton(
                      onPressed: () => openLink(
                        'https://console.cloud.google.com/apis/credentials',
                      ),
                      child: const AppText('Open Google Cloud credentials'),
                    ),
                  ),
                  field('OAuth client ID', clientId),
                  field(
                    'OAuth client secret',
                    clientSecret,
                    secret: true,
                    help: data['has_client_secret'] == true
                        ? 'Saved securely. Leave blank to keep it.'
                        : null,
                    validate: (value) =>
                        (value?.isEmpty ?? true) &&
                            data['has_client_secret'] != true
                        ? 'Enter the client secret'
                        : null,
                  ),
                  field(
                    'Authorized callback URL',
                    callback,
                    help:
                        'Register this exact URL with Google. Open AirLink at this same domain when connecting.',
                  ),
                  field('Backup folder name', folder),
                  field(
                    'Backup encryption password',
                    password,
                    secret: true,
                    help:
                        'Keep this password outside AirLink. It is required to recover your backup. ${data['has_backup_password'] == true ? 'Leave blank to keep the saved password.' : ''}',
                    validate: (value) =>
                        (value?.isEmpty ?? true) &&
                            data['has_backup_password'] == true
                        ? null
                        : (value?.length ?? 0) < 12
                        ? 'Use at least 12 characters'
                        : null,
                  ),
                  field(
                    'Confirm backup password',
                    confirm,
                    secret: true,
                    validate: (value) => value != password.text
                        ? 'Passwords do not match'
                        : null,
                  ),
                  SwitchListTile(
                    contentPadding: EdgeInsets.zero,
                    title: const AppText('Weekly automatic backup'),
                    value: automatic,
                    onChanged: (value) => setState(() {
                      automatic = value;
                      dirty = true;
                    }),
                  ),
                  DropdownButtonFormField<int>(
                    initialValue: weekday,
                    key: ValueKey(weekday),
                    decoration: const InputDecoration(labelText: 'Backup day'),
                    items: [
                      for (var i = 0; i < days.length; i++)
                        DropdownMenuItem(value: i, child: Text(days[i])),
                    ],
                    onChanged: (value) => setState(() {
                      weekday = value!;
                      dirty = true;
                    }),
                  ),
                  const SizedBox(height: 12),
                  field('Backup time (HH:MM)', clock),
                  field(
                    'Schedule timezone',
                    zone,
                    help: 'For example: Europe/Zurich, Asia/Baghdad or UTC.',
                  ),
                  const AppText(
                    'Weekly backups continue while you are logged out. Existing backups are kept until you delete them. Changing the encryption password affects new backups only.',
                  ),
                  const SizedBox(height: 12),
                  Wrap(
                    spacing: 12,
                    runSpacing: 8,
                    children: [
                      FilledButton(
                        onPressed: busy || running ? null : save,
                        child: const AppText('Save backup settings'),
                      ),
                      OutlinedButton(
                        onPressed:
                            busy ||
                                running ||
                                dirty ||
                                data['has_client_secret'] != true
                            ? null
                            : connect,
                        child: AppText(
                          data['connected'] == true
                              ? 'Reconnect Google Drive'
                              : 'Connect Google Drive',
                        ),
                      ),
                      if (data['connected'] == true)
                        TextButton(
                          onPressed: busy || running
                              ? null
                              : () => action('/disconnect'),
                          child: const AppText('Disconnect Google Drive'),
                        ),
                    ],
                  ),
                  if (dirty)
                    const AppText(
                      'Save your changes before connecting Google Drive.',
                    ),
                ],
              ),
            ),
          ),
        ),
        if ((status['history'] as List? ?? []).isNotEmpty)
          Card(
            child: Padding(
              padding: const EdgeInsets.all(16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    'Recent backups',
                    style: Theme.of(context).textTheme.titleMedium,
                  ),
                  for (final entry in status['history'])
                    ListTile(
                      contentPadding: EdgeInsets.zero,
                      title: Text(
                        '${entry['status']} · ${date(entry['started_at'])}',
                      ),
                      subtitle: entry['error'] != null
                          ? Text(entry['error'])
                          : Text(entry['backup']?['filename'] ?? ''),
                      trailing: entry['backup']?['file_url'] != null
                          ? TextButton(
                              onPressed: () =>
                                  openLink(entry['backup']['file_url']),
                              child: const AppText('Open in Drive'),
                            )
                          : null,
                    ),
                ],
              ),
            ),
          ),
      ],
    );
  }
}
