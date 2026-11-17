import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'api.dart';
import 'backup_picker.dart';
import 'backup_selection.dart';

class LocalUpdateDialog extends StatefulWidget {
  const LocalUpdateDialog({
    super.key,
    required this.api,
    this.pickFile = pickUpdateFile,
  });
  final Api api;
  final Future<BackupSelection?> Function() pickFile;

  @override
  State<LocalUpdateDialog> createState() => _LocalUpdateDialogState();
}

class _LocalUpdateDialogState extends State<LocalUpdateDialog> {
  BackupSelection? file;
  String? token, error;
  Map<String, dynamic>? release;
  bool busy = false, cancelled = false;
  int sent = 0;

  Future<dynamic> request(String action, Map<String, dynamic> body) =>
      widget.api.request('/updates/local/$action', method: 'POST', body: body);

  Future<void> browse() async {
    try {
      final selected = await widget.pickFile();
      if (!mounted || selected == null) return;
      if (!selected.name.toLowerCase().endsWith('.airlink-update') ||
          selected.size <= 0 ||
          selected.size > 2 * 1024 * 1024 * 1024 + 256 * 1024) {
        throw Exception(
          'Choose the signed .airlink-update file from an AirLink release.',
        );
      }
      setState(() {
        file = selected;
        release = null;
        error = null;
        sent = 0;
      });
    } catch (e) {
      if (mounted) setState(() => error = e.toString());
    }
  }

  Future<void> upload() async {
    final selected = file!;
    setState(() {
      busy = true;
      cancelled = false;
      error = null;
      sent = 0;
      release = null;
    });
    try {
      final started = await request('start', {'size': selected.size});
      token = started['token'];
      for (int offset = 0; offset < selected.size;) {
        if (!mounted || cancelled) return;
        final end = (offset + 32768).clamp(0, selected.size);
        final bytes = await selected.read(offset, end);
        if (!mounted || cancelled) return;
        if (bytes.length != end - offset) {
          throw Exception(
            'Could not read the complete update file. Browse and try again.',
          );
        }
        final result = await request('chunk', {
          'token': token,
          'offset': offset,
          'data': base64Encode(bytes),
        });
        if (result['received'] != end) {
          throw Exception('Upload incomplete. Browse and try again.');
        }
        offset = end;
        if (mounted) setState(() => sent = offset);
      }
      if (!mounted || cancelled) return;
      final result = await request('finish', {'token': token});
      if (mounted && !cancelled) {
        setState(() => release = Map<String, dynamic>.from(result['release']));
      }
    } catch (e) {
      if (mounted) setState(() => error = e.toString());
    } finally {
      if (cancelled || !mounted) {
        try {
          await cleanup();
        } catch (e) {
          if (mounted) setState(() => error = e.toString());
        }
      }
      if (mounted) {
        setState(() {
          busy = false;
          cancelled = false;
        });
      }
    }
  }

  Future<void> cleanup() async {
    if (token != null) {
      await request('cancel', {'token': token});
      token = null;
    }
  }

  Future<void> close() async {
    if (busy) {
      setState(() => cancelled = true);
      return;
    }
    setState(() => busy = true);
    try {
      await cleanup();
      if (mounted) Navigator.pop(context);
    } catch (e) {
      if (mounted) {
        setState(() {
          error = e.toString();
          busy = false;
        });
      }
    }
  }

  @override
  void dispose() {
    if (!busy && release == null) {
      cleanup().catchError((Object _) {});
    }
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => PopScope(
    canPop: !busy && token == null,
    child: AlertDialog(
      title: const Text('Update from file'),
      content: SizedBox(
        width: 520,
        child: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text(
                'Download the .airlink-update file from an AirLink GitHub release on any computer, then browse for it here. The AirLink server does not need internet access.',
              ),
              TextButton.icon(
                onPressed: () async {
                  await Clipboard.setData(
                    const ClipboardData(
                      text:
                          'https://github.com/safin97/airlink-isp-os/releases/latest',
                    ),
                  );
                  if (context.mounted) {
                    ScaffoldMessenger.of(context).showSnackBar(
                      const SnackBar(
                        content: Text('Release download link copied'),
                      ),
                    );
                  }
                },
                icon: const Icon(Icons.copy_outlined),
                label: const Text('Copy release download link'),
              ),
              const SizedBox(height: 16),
              OutlinedButton.icon(
                onPressed: busy ? null : browse,
                icon: const Icon(Icons.folder_open),
                label: const Text('Browse update file'),
              ),
              if (file != null) ...[
                const SizedBox(height: 12),
                Text(
                  '${file!.name} · ${(file!.size / (1024 * 1024)).toStringAsFixed(1)} MB',
                ),
              ],
              if (busy) ...[
                const SizedBox(height: 12),
                Text(
                  cancelled
                      ? 'Cancelling upload…'
                      : sent == file?.size
                      ? 'Verifying signature and package…'
                      : 'Uploading update from this computer…',
                ),
                const SizedBox(height: 8),
                LinearProgressIndicator(
                  value: file != null && sent < file!.size
                      ? sent / file!.size
                      : null,
                ),
              ],
              if (error != null)
                Padding(
                  padding: const EdgeInsets.symmetric(vertical: 12),
                  child: Text(
                    error!,
                    style: TextStyle(
                      color: Theme.of(context).colorScheme.error,
                    ),
                  ),
                ),
              if (release != null) ...[
                const SizedBox(height: 16),
                Text(
                  'Verified release: ${release!['version']}',
                  style: Theme.of(context).textTheme.titleMedium,
                ),
                const Text(
                  'Publisher signature and package verified. Installing backs up the database and briefly pauses monitoring while services restart.',
                ),
                if (release!['reboot_required'] == true)
                  const Text(
                    'A system restart is required after installation.',
                  ),
                const SizedBox(height: 12),
                Text(release!['release_notes']?.toString() ?? ''),
              ],
            ],
          ),
        ),
      ),
      actions: [
        TextButton(
          onPressed: cancelled ? null : close,
          child: Text(busy ? 'Cancel upload' : 'Cancel'),
        ),
        if (release == null)
          FilledButton(
            onPressed: busy || file == null ? null : upload,
            child: const Text('Upload and verify'),
          )
        else
          FilledButton(
            onPressed: busy
                ? null
                : () => Navigator.pop(context, {
                    ...release!,
                    'upload_token': token,
                  }),
            child: const Text('Install verified update'),
          ),
      ],
    ),
  );
}
