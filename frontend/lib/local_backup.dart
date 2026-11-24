import 'section_access.dart';
import 'dart:async';
import 'dart:typed_data';
import 'package:flutter/material.dart';
import 'api.dart';
import 'backup_file.dart';
import 'mega_restore.dart';

class LocalBackup extends StatefulWidget {
  const LocalBackup({
    super.key,
    required this.api,
    this.saveFile = saveBackupFile,
  });
  final Api api;
  final Future<void> Function(Uint8List, String) saveFile;

  @override
  State<LocalBackup> createState() => _LocalBackupState();
}

class _LocalBackupState extends State<LocalBackup> {
  final password = TextEditingController();
  final confirm = TextEditingController();
  final form = GlobalKey<FormState>();
  Map<String, dynamic>? job;
  String? error, message;
  bool busy = false, polling = false;
  Timer? timer;
  bool get creating => job?['status'] == 'creating';
  static const path = '/backups/downloads';

  @override
  void dispose() {
    timer?.cancel();
    password.dispose();
    confirm.dispose();
    super.dispose();
  }

  Future<void> create() async {
    if (!form.currentState!.validate()) return;
    setState(() {
      busy = true;
      error = null;
      message = null;
    });
    try {
      final next = Map<String, dynamic>.from(
        await widget.api.request(
          path,
          method: 'POST',
          body: {'password': password.text},
        ),
      );
      if (!mounted) return;
      password.clear();
      confirm.clear();
      setState(() => job = next);
      timer?.cancel();
      timer = Timer.periodic(const Duration(seconds: 2), (_) => poll());
    } catch (e) {
      if (mounted) setState(() => error = e.toString());
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> poll() async {
    if (polling || job == null) return;
    polling = true;
    try {
      final next = Map<String, dynamic>.from(
        await widget.api.request('$path/${job!['id']}'),
      );
      if (!mounted) return;
      setState(() {
        job = next;
        error = next['error'] as String?;
      });
      if (!creating) timer?.cancel();
    } catch (e) {
      if (mounted) setState(() => error = e.toString());
      // A transient network error does not lose the in-progress job.
      if (e is ApiException && e.status == 409) {
        timer?.cancel();
        if (mounted) setState(() => job = null);
      }
    } finally {
      polling = false;
    }
  }

  Future<void> download() async {
    setState(() {
      busy = true;
      error = null;
      message = null;
    });
    try {
      final bytes =
          await widget.api.request('$path/${job!['id']}/file', binary: true)
              as Uint8List;
      if (bytes.length != job!['size']) {
        throw Exception('Incomplete download. Please retry.');
      }
      await widget.saveFile(bytes, job!['filename'] as String);
      if (mounted) {
        setState(
          () => message =
              'Backup sent to your browser. Keep the file and its password in a safe place.',
        );
      }
    } catch (e) {
      if (mounted) setState(() => error = e.toString());
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    if (!hasSection(widget.api.user ?? {}, 'backups')) {
      return const SizedBox.shrink();
    }
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Form(
          key: form,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                'Download a backup',
                style: Theme.of(context).textTheme.titleLarge,
              ),
              const SizedBox(height: 8),
              const Text(
                'Save an encrypted backup to your computer or restore a saved backup file. '
                'On the appliance this includes the database and configuration; in local mode it includes the local database and recovery key.',
              ),
              const SizedBox(height: 12),
              TextFormField(
                controller: password,
                obscureText: true,
                enableSuggestions: false,
                autocorrect: false,
                enabled: !busy && !creating,
                decoration: const InputDecoration(
                  labelText: 'Download backup password',
                  helperText:
                      'At least 12 characters. Keep this password: it is required to recover the backup.',
                  helperMaxLines: 2,
                ),
                validator: (value) =>
                    (value?.length ?? 0) < 12 || (value?.length ?? 0) > 1024
                    ? 'Use 12–1024 characters'
                    : null,
              ),
              const SizedBox(height: 12),
              TextFormField(
                controller: confirm,
                obscureText: true,
                enableSuggestions: false,
                autocorrect: false,
                enabled: !busy && !creating,
                decoration: const InputDecoration(
                  labelText: 'Confirm download password',
                ),
                validator: (value) =>
                    value != password.text ? 'Passwords do not match' : null,
              ),
              const SizedBox(height: 16),
              Wrap(
                spacing: 12,
                runSpacing: 12,
                children: [
                  FilledButton.icon(
                    onPressed:
                        !canEditSection(widget.api.user ?? {}, 'backups') ||
                            busy ||
                            creating
                        ? null
                        : create,
                    icon: const Icon(Icons.backup_outlined),
                    label: const Text('Create backup'),
                  ),
                  OutlinedButton.icon(
                    onPressed:
                        !canEditSection(widget.api.user ?? {}, 'backups') ||
                            busy ||
                            creating
                        ? null
                        : () => showDialog<void>(
                            context: context,
                            barrierDismissible: false,
                            builder: (_) => MegaRestoreDialog(
                              api: widget.api,
                              fromComputer: true,
                            ),
                          ),
                    icon: const Icon(Icons.restore),
                    label: const Text('Restore from PC file'),
                  ),
                  if (job?['status'] == 'ready')
                    OutlinedButton.icon(
                      onPressed: busy ? null : download,
                      icon: const Icon(Icons.download),
                      label: const Text('Download backup'),
                    ),
                ],
              ),
              if (!canEditSection(widget.api.user ?? {}, 'backups') ||
                  busy ||
                  creating) ...[
                const SizedBox(height: 12),
                const LinearProgressIndicator(),
                Text(
                  creating
                      ? 'Creating your encrypted backup… Keep this page open.'
                      : 'Preparing download…',
                ),
              ],
              if (job?['status'] == 'ready') ...[
                const SizedBox(height: 12),
                const Text(
                  'Backup ready. Download it within one hour. Server restarts invalidate pending downloads.',
                ),
              ],
              if (error != null)
                Padding(
                  padding: const EdgeInsets.only(top: 12),
                  child: Text(
                    error!,
                    style: TextStyle(
                      color: Theme.of(context).colorScheme.error,
                    ),
                  ),
                ),
              if (message != null)
                Padding(
                  padding: const EdgeInsets.only(top: 12),
                  child: Text(message!),
                ),
            ],
          ),
        ),
      ),
    );
  }
}
