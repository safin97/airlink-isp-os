import 'dart:async';
import 'dart:convert';
import 'package:flutter/material.dart';
import 'api.dart';
import 'backup_picker.dart';
import 'backup_selection.dart';

class MegaRestoreDialog extends StatefulWidget {
  const MegaRestoreDialog({
    super.key,
    required this.api,
    this.fromComputer = false,
    this.pickFile = pickBackupFile,
  });
  final Api api;
  final bool fromComputer;
  final Future<BackupSelection?> Function() pickFile;
  @override
  State<MegaRestoreDialog> createState() => _MegaRestoreDialogState();
}

class _MegaRestoreDialogState extends State<MegaRestoreDialog> {
  static const path = '/backups/mega';
  String get restorePath =>
      widget.fromComputer ? '/backups/restore' : '$path/restore';
  BackupSelection? file;
  int sent = 0;
  bool uploading = false;
  final password = TextEditingController(),
      confirmation = TextEditingController();
  List<dynamic> files = [];
  Map<String, dynamic> state = {};
  String? selected, error;
  bool busy = false, fetching = false;
  int generation = 0, listVersion = 0;
  Timer? timer;
  String get status => state['status'] ?? '';
  bool get working => ['downloading', 'checking', 'restoring'].contains(status);
  bool get pending => status == 'awaiting_restart';

  @override
  void initState() {
    super.initState();
    if (widget.api.user?['role'] == 'owner') {
      initialize();
      timer = Timer.periodic(const Duration(seconds: 3), (_) => poll());
    }
  }

  @override
  void dispose() {
    timer?.cancel();
    password.dispose();
    confirmation.dispose();
    super.dispose();
  }

  Future<void> initialize() async {
    await poll();
    if (!widget.fromComputer &&
        mounted &&
        !working &&
        !pending &&
        status != 'ready' &&
        status != 'uploading') {
      await list();
    }
  }

  Future<void> poll() async {
    if (busy || fetching) return;
    fetching = true;
    final current = generation;
    try {
      final result = Map<String, dynamic>.from(
        await widget.api.request(restorePath),
      );
      if (mounted && !busy && current == generation) {
        setState(() => state = result);
      }
    } catch (e) {
      if (mounted && current == generation) {
        setState(() => error = e.toString());
      }
    } finally {
      fetching = false;
    }
  }

  Future<void> list() async {
    generation++;
    setState(() {
      busy = true;
      error = null;
    });
    try {
      final result = await widget.api.request('$path/files');
      if (mounted) {
        setState(() {
          files = result['files'] as List;
          selected = null;
          listVersion++;
        });
      }
    } catch (e) {
      if (mounted) setState(() => error = e.toString());
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> action(String name, [Object? body]) async {
    generation++;
    setState(() {
      busy = true;
      error = null;
    });
    try {
      final result = Map<String, dynamic>.from(
        await widget.api.request(
          '$restorePath/$name',
          method: 'POST',
          body: body,
        ),
      );
      if (!mounted) return;
      password.clear();
      confirmation.clear();
      if (mounted) setState(() => state = result);
    } catch (e) {
      if (mounted) setState(() => error = e.toString());
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> browse() async {
    try {
      final selection = await widget.pickFile();
      if (!mounted || selection == null) return;
      if (!selection.name.toLowerCase().endsWith('.tar.airlink') ||
          selection.size <= 0 ||
          selection.size > 20 * 1024 * 1024 * 1024) {
        throw Exception(
          'Choose an encrypted .tar.airlink backup, up to 20 GiB.',
        );
      }
      setState(() {
        file = selection;
        selected = selection.name;
        error = null;
      });
    } catch (e) {
      if (mounted) setState(() => error = e.toString());
    }
  }

  Future<void> upload() async {
    final selectedFile = file!;
    generation++;
    setState(() {
      busy = true;
      uploading = true;
      sent = 0;
      error = null;
    });
    try {
      final started = await widget.api.request(
        '$restorePath/uploads',
        method: 'POST',
        body: {'filename': selectedFile.name, 'size': selectedFile.size},
      );
      if (!mounted) return;
      setState(() => state = Map<String, dynamic>.from(started));
      for (int offset = 0; offset < selectedFile.size;) {
        if (!mounted) return;
        final end = (offset + 32768).clamp(0, selectedFile.size);
        final bytes = await selectedFile.read(offset, end);
        if (bytes.length != end - offset) {
          throw Exception(
            'Could not read the complete backup file. Browse and try again.',
          );
        }
        final result = await widget.api.request(
          '$restorePath/uploads',
          method: 'PUT',
          body: {
            'token': started['token'],
            'offset': offset,
            'data': base64Encode(bytes),
          },
        );
        if (result['received'] != end) {
          throw Exception('Upload incomplete. Browse and try again.');
        }
        offset = end;
        if (mounted) setState(() => sent = offset);
      }
      final result = await widget.api.request(
        '$restorePath/prepare',
        method: 'POST',
        body: {'token': started['token'], 'password': password.text},
      );
      if (!mounted) return;
      password.clear();
      setState(() => state = Map<String, dynamic>.from(result));
    } catch (e) {
      if (mounted) setState(() => error = e.toString());
    } finally {
      if (mounted) {
        setState(() {
          busy = false;
          uploading = false;
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    if (widget.api.user?['role'] != 'owner') return const SizedBox.shrink();
    final locked = busy || working || pending;
    return PopScope(
      canPop: !uploading,
      child: AlertDialog(
        title: Text(
          widget.fromComputer ? 'Restore from PC file' : 'Restore from MEGA',
        ),
        content: SizedBox(
          width: 620,
          child: SingleChildScrollView(
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                const Text(
                  'Restore replaces the current AirLink database with the selected backup. '
                  'Changes made since that backup will be lost. A safety copy is saved before replacement. '
                  'You will need to sign in using an account and password from the backup.',
                ),
                const SizedBox(height: 12),
                if (busy || working) const LinearProgressIndicator(),
                if (uploading && file != null)
                  Text(
                    'Uploading: ${(sent / file!.size * 100).toStringAsFixed(0)}% — keep this window open.',
                  ),
                if (status.isNotEmpty) Text('Recovery status: $status'),
                if (state['filename'] != null)
                  Text('Selected backup: ${state['filename']}'),
                if (state['message'] != null) SelectableText(state['message']),
                if (state['safety_backup'] != null)
                  SelectableText('Safety copy: ${state['safety_backup']}'),
                if (error != null || state['error'] != null)
                  Text(
                    error ?? state['error'],
                    style: TextStyle(
                      color: Theme.of(context).colorScheme.error,
                    ),
                  ),
                if (status == 'ready') ...[
                  const SizedBox(height: 12),
                  Text(
                    state['local_mode'] == true
                        ? 'After confirmation, stop the local server and start it again with ./scripts/live.sh to apply recovery.'
                        : 'After confirmation, AirLink services will stop briefly while the database is restored. Network settings are kept.',
                  ),
                  TextField(
                    controller: confirmation,
                    enabled: !locked,
                    onChanged: (_) => setState(() {}),
                    decoration: const InputDecoration(
                      labelText: 'Type RESTORE to replace current data',
                    ),
                  ),
                  const SizedBox(height: 12),
                  FilledButton(
                    onPressed:
                        locked ||
                            confirmation.text != 'RESTORE' ||
                            state['token'] == null
                        ? null
                        : () => action('confirm', {
                            'token': state['token'],
                            'confirmation': confirmation.text,
                          }),
                    child: const Text('Confirm restore'),
                  ),
                  TextButton(
                    onPressed: locked ? null : () => action('cancel'),
                    child: const Text('Cancel prepared restore'),
                  ),
                ] else if (status == 'uploading') ...[
                  const Text(
                    'An upload is in progress or was interrupted. Cancel it before selecting another backup.',
                  ),
                  TextButton(
                    onPressed: busy || state['token'] == null
                        ? null
                        : () => action('cancel'),
                    child: const Text('Cancel file upload'),
                  ),
                ] else if (!working && !pending) ...[
                  const SizedBox(height: 12),
                  if (widget.fromComputer) ...[
                    OutlinedButton.icon(
                      onPressed: busy ? null : browse,
                      icon: const Icon(Icons.folder_open),
                      label: const Text('Browse backup file'),
                    ),
                    if (file != null)
                      Text('${file!.name} (${file!.size} bytes)'),
                  ] else ...[
                    OutlinedButton(
                      onPressed: busy ? null : list,
                      child: const Text('Refresh MEGA backups'),
                    ),
                    if (files.isEmpty && !busy)
                      const Text(
                        'No backups listed. Refresh to load backups from the configured MEGA folder.',
                      ),
                    if (files.isNotEmpty)
                      DropdownButtonFormField<String>(
                        key: ValueKey(listVersion),
                        initialValue: selected,
                        isExpanded: true,
                        decoration: const InputDecoration(
                          labelText: 'Backup to restore',
                        ),
                        items: [
                          for (final file in files)
                            DropdownMenuItem(
                              value: file['filename'] as String,
                              child: Text(
                                '${file['filename']} (${file['size']} bytes)',
                                overflow: TextOverflow.ellipsis,
                              ),
                            ),
                        ],
                        onChanged: busy
                            ? null
                            : (value) => setState(() => selected = value),
                      ),
                  ],
                  TextField(
                    controller: password,
                    enabled: !busy,
                    obscureText: true,
                    autocorrect: false,
                    enableSuggestions: false,
                    onChanged: (_) => setState(() {}),
                    decoration: const InputDecoration(
                      labelText: 'Backup encryption password',
                      helperText:
                          'Use the password that encrypted this backup, even if you changed it later.',
                    ),
                  ),
                  const SizedBox(height: 12),
                  FilledButton(
                    onPressed:
                        busy || selected == null || password.text.length < 12
                        ? null
                        : widget.fromComputer
                        ? upload
                        : () => action('prepare', {
                            'filename': selected,
                            'password': password.text,
                          }),
                    child: Text(
                      widget.fromComputer
                          ? 'Upload and verify backup'
                          : 'Download and verify backup',
                    ),
                  ),
                ],
              ],
            ),
          ),
        ),
        actions: [
          TextButton(
            onPressed: uploading ? null : () => Navigator.of(context).pop(),
            child: const Text('Close'),
          ),
        ],
      ),
    );
  }
}
