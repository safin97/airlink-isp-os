import 'dart:async';
import 'package:flutter/material.dart';
import 'package:xterm/xterm.dart';
import 'api.dart';

// Bound dimensions even when a command emits an application resize sequence.
class SystemShellTerminal extends Terminal {
  SystemShellTerminal() : super(maxLines: 2000);

  @override
  void resize(int newWidth, int newHeight, [int? pixelWidth, int? pixelHeight]) {
    super.resize(
      newWidth.clamp(20, 300),
      newHeight.clamp(5, 120),
      pixelWidth,
      pixelHeight,
    );
  }
}

class SystemTerminalButton extends StatelessWidget {
  const SystemTerminalButton({super.key, required this.api});
  final Api api;

  @override
  Widget build(BuildContext context) {
    if (api.user?['role'] != 'owner') return const SizedBox.shrink();
    return OutlinedButton.icon(
      icon: const Icon(Icons.terminal),
      label: const Text('System terminal'),
      onPressed: () => showDialog<void>(
        context: context,
        barrierDismissible: false,
        builder: (_) => SystemTerminalDialog(api: api),
      ),
    );
  }
}

class SystemTerminalDialog extends StatefulWidget {
  const SystemTerminalDialog({super.key, required this.api});
  final Api api;

  @override
  State<SystemTerminalDialog> createState() => _SystemTerminalDialogState();
}

class _SystemTerminalDialogState extends State<SystemTerminalDialog> {
  final password = TextEditingController();
  final terminal = SystemShellTerminal();
  final focus = FocusNode();
  Timer? timer;
  String? session;
  String? error;
  String? reason;
  String pending = '';
  int cursor = 0;
  int sequence = 0;
  int cols = 100;
  int rows = 30;
  bool checking = true;
  bool supported = false;
  bool opening = false;
  bool exchanging = false;
  bool closing = false;
  bool ended = false;

  @override
  void initState() {
    super.initState();
    terminal.onOutput = enqueue;
    terminal.onResize = (width, height, _, _) {
      cols = width.clamp(20, 300);
      rows = height.clamp(5, 120);
    };
    check();
  }

  Future<void> check() async {
    try {
      final data = await widget.api.request('/system/terminal');
      if (!mounted) return;
      setState(() {
        supported = data['supported'] == true;
        reason = data['reason'] as String?;
      });
    } catch (e) {
      if (mounted) setState(() => error = e.toString());
    } finally {
      if (mounted) setState(() => checking = false);
    }
  }

  Future<void> open() async {
    if (opening || !supported || password.text.isEmpty) return;
    setState(() {
      opening = true;
      error = null;
    });
    try {
      final data = await widget.api.request(
        '/system/terminal/open',
        method: 'POST',
        body: {'password': password.text, 'cols': cols, 'rows': rows},
      );
      final id = data['session_id'] as String;
      if (!mounted) {
        await closeRemote(id);
        return;
      }
      password.clear();
      setState(() => session = id);
      terminal.write(
        'AirLink system terminal — ROOT ACCESS\r\n'
        'Commands run on this AirLink PC. Session limit: 15 minutes.\r\n\r\n',
      );
      timer = Timer.periodic(
        const Duration(milliseconds: 200),
        (_) => exchange(),
      );
      await exchange();
      focus.requestFocus();
    } catch (e) {
      if (mounted) setState(() => error = e.toString());
    } finally {
      if (mounted) setState(() => opening = false);
    }
  }

  void enqueue(String text) {
    if (session == null || ended || closing) return;
    if (pending.length + text.length > 32768) {
      setState(() => error = 'Paste is too large. Send smaller sections.');
      return;
    }
    pending += text;
  }

  Future<void> exchange() async {
    if (exchanging || ended || closing || session == null) return;
    exchanging = true;
    // Keep Unicode surrogate pairs intact at chunk boundaries.
    var length = pending.length.clamp(0, 2048);
    if (length > 0 &&
        length < pending.length &&
        pending.codeUnitAt(length - 1) >= 0xD800 &&
        pending.codeUnitAt(length - 1) <= 0xDBFF) {
      length--;
    }
    final input = pending.substring(0, length);
    pending = pending.substring(length);
    if (input.isNotEmpty) sequence++;
    try {
      final result = await widget.api
          .request(
            '/system/terminal/exchange',
            method: 'POST',
            body: {
              'session_id': session,
              'data': input,
              'sequence': sequence,
              'cursor': cursor,
              'cols': cols,
              'rows': rows,
            },
          )
          .timeout(const Duration(seconds: 15));
      if (!mounted || closing) return;
      if (result['truncated'] == true) {
        terminal.write('\r\n[Older output omitted]\r\n');
      }
      terminal.write(result['output'] as String? ?? '');
      cursor = result['cursor'] as int;
      if (result['closed'] == true) {
        timer?.cancel();
        setState(() {
          ended = true;
          reason = result['reason'] as String? ?? 'Terminal closed';
        });
      }
    } catch (e) {
      timer?.cancel();
      if (mounted) {
        setState(() {
          ended = true;
          error =
              'Connection ended: $e. Commands are not resent. Close and reopen the terminal.';
        });
      }
      final id = session;
      if (id != null) unawaited(closeRemote(id));
    } finally {
      exchanging = false;
    }
  }

  Future<void> closeRemote(String id) async {
    try {
      await widget.api
          .request(
            '/system/terminal/close',
            method: 'POST',
            body: {'session_id': id},
          )
          .timeout(const Duration(seconds: 10));
    } catch (_) {
      // The controller also expires sessions after 90 seconds without exchanges.
    }
  }

  Future<void> close() async {
    if (closing || opening) return;
    setState(() => closing = true);
    timer?.cancel();
    final id = session;
    session = null;
    if (id != null) await closeRemote(id);
    if (mounted) Navigator.of(context).pop();
  }

  @override
  void dispose() {
    timer?.cancel();
    terminal.onOutput = null;
    terminal.onResize = null;
    final id = session;
    if (id != null) unawaited(closeRemote(id));
    password.dispose();
    focus.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final active = session != null;
    return PopScope(
      canPop: !opening && !closing,
      child: Dialog(
        insetPadding: const EdgeInsets.all(16),
        child: SizedBox(
          width: active ? 1100 : 520,
          height: active ? MediaQuery.sizeOf(context).height * .85 : null,
          child: Padding(
            padding: const EdgeInsets.all(20),
            child: Column(
              mainAxisSize: active ? MainAxisSize.max : MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                const Text(
                  'System terminal',
                  style: TextStyle(fontSize: 22, fontWeight: FontWeight.w600),
                ),
                const SizedBox(height: 8),
                const Text('Owner only · Root access to this AirLink PC'),
                const SizedBox(height: 12),
                if (checking || opening || closing)
                  const LinearProgressIndicator(),
                if (error != null)
                  Padding(
                    padding: const EdgeInsets.symmetric(vertical: 8),
                    child: Text(
                      error!,
                      style: TextStyle(
                        color: Theme.of(context).colorScheme.error,
                      ),
                    ),
                  ),
                if (reason != null)
                  Padding(
                    padding: const EdgeInsets.symmetric(vertical: 8),
                    child: Text(reason!),
                  ),
                if (!active && supported) ...[
                  const Text(
                    'Enter your owner password to open the shell. Commands can change the system. '
                    'Closing this window stops the shell and its commands. Sessions expire after 15 minutes.',
                  ),
                  const SizedBox(height: 16),
                  TextField(
                    controller: password,
                    obscureText: true,
                    autocorrect: false,
                    enableSuggestions: false,
                    enabled: !opening,
                    decoration: const InputDecoration(
                      labelText: 'Owner password',
                      border: OutlineInputBorder(),
                    ),
                    onSubmitted: (_) => open(),
                  ),
                ],
                if (active) ...[
                  Expanded(
                    child: TerminalView(
                      terminal,
                      focusNode: focus,
                      autofocus: true,
                      readOnly: ended || closing,
                      textStyle: const TerminalStyle(fontSize: 14),
                    ),
                  ),
                  const SizedBox(height: 8),
                  Wrap(
                    spacing: 8,
                    children: [
                      TextButton(
                        onPressed: ended || closing
                            ? null
                            : () => enqueue('\x03'),
                        child: const Text('Ctrl+C'),
                      ),
                      TextButton(
                        onPressed: ended || closing
                            ? null
                            : () => enqueue('\t'),
                        child: const Text('Tab'),
                      ),
                      TextButton(
                        onPressed: ended || closing
                            ? null
                            : () => enqueue('\x1b'),
                        child: const Text('Esc'),
                      ),
                      TextButton(
                        onPressed: ended || closing
                            ? null
                            : () => enqueue('\r'),
                        child: const Text('Enter'),
                      ),
                    ],
                  ),
                ],
                const SizedBox(height: 16),
                Row(
                  mainAxisAlignment: MainAxisAlignment.end,
                  children: [
                    TextButton(
                      onPressed: opening || closing ? null : close,
                      child: Text(active ? 'Close terminal' : 'Close'),
                    ),
                    if (!active && supported) ...[
                      const SizedBox(width: 8),
                      FilledButton(
                        onPressed: opening ? null : open,
                        child: const Text('Open terminal'),
                      ),
                    ],
                  ],
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
