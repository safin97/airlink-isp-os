import 'dart:async';
import 'package:flutter/material.dart';
import 'api.dart';
import 'app_language.dart';
import 'client_speed_test.dart';

class ClientConnection extends StatefulWidget {
  final Api api;
  final ClientSpeedTest Function()? testFactory;
  const ClientConnection({super.key, required this.api, this.testFactory});
  @override
  State<ClientConnection> createState() => _ClientConnectionState();
}

class _ClientConnectionState extends State<ClientConnection> {
  Map<String, dynamic>? connection;
  Map<String, double>? speeds;
  String? signalError, testMessage;
  bool refreshing = false, testing = false;
  ClientSpeedTest? activeTest;
  Timer? timer;
  int generation = 0;

  @override
  void initState() {
    super.initState();
    refresh();
    timer = Timer.periodic(const Duration(seconds: 30), (_) => refresh());
  }

  @override
  void dispose() {
    timer?.cancel();
    activeTest?.close();
    super.dispose();
  }

  Future<void> refresh() async {
    if (refreshing || testing) return;
    setState(() => refreshing = true);
    try {
      final data = await widget.api.request('/client/connection', retry: false);
      if (mounted) {
        setState(() {
          connection = Map<String, dynamic>.from(data);
          signalError = null;
        });
      }
    } catch (_) {
      if (mounted) {
        setState(() {
          connection = null;
          signalError = 'Device readings are unavailable. Try refreshing.';
        });
      }
    } finally {
      if (mounted) setState(() => refreshing = false);
    }
  }

  void stop() {
    generation++;
    activeTest?.close();
    setState(() {
      testing = false;
      testMessage = 'Test stopped.';
    });
  }

  Future<void> test({required bool speed}) async {
    if (testing) return;
    final current = ++generation;
    final runner = widget.testFactory?.call() ?? ClientSpeedTest();
    activeTest = runner;
    setState(() {
      testing = true;
      speeds = null;
      testMessage = 'Checking internet…';
    });
    try {
      if (speed) {
        final result = await runner.run((stage) {
          if (mounted && current == generation) {
            setState(() => testMessage = stage);
          }
        });
        if (mounted && current == generation) {
          setState(() {
            speeds = result;
            testMessage = 'Speed test complete.';
          });
        }
      } else {
        final latency = await runner.checkInternet();
        if (mounted && current == generation) {
          setState(
            () => testMessage =
                'Internet reachable • ${latency.toStringAsFixed(0)} ms HTTP response',
          );
        }
      }
    } catch (_) {
      if (mounted && current == generation) {
        setState(
          () => testMessage =
              'Could not reach the test server. Your connection may be offline, slow, or blocking this test. Try again.',
        );
      }
    } finally {
      runner.close();
      if (mounted && current == generation) setState(() => testing = false);
    }
  }

  String get signalNote {
    if (signalError != null) return signalError!;
    return switch (connection?['status']) {
      'offline' => 'Your PPPoE service is offline.',
      'ambiguous' =>
        'Multiple active sessions. A single wireless signal cannot be identified.',
      'connecting' || 'pending' => 'Reading your wireless device…',
      'disabled' => 'Wireless monitoring is disabled by your provider.',
      _ =>
        'Signal is unavailable. Your provider needs a reachable device with supported SNMP or device access.',
    };
  }

  @override
  Widget build(BuildContext context) {
    final signal = connection?['signal_dbm'];
    final stamp = DateTime.tryParse(connection?['collected_at'] ?? '');
    final fresh =
        stamp != null && DateTime.now().difference(stamp).inSeconds <= 90;
    return Card.outlined(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            Text(
              tr('My connection'),
              style: Theme.of(context).textTheme.titleLarge,
            ),
            const SizedBox(height: 16),
            Text(
              '${tr('Wireless signal')}: ${signal != null && fresh ? '$signal dBm' : '—'}',
              style: Theme.of(context).textTheme.titleMedium,
            ),
            const SizedBox(height: 8),
            const AppText(
              'Signal from your ISP wireless device, when available.',
            ),
            if (signal == null || !fresh) AppText(signalNote),
            if (signal != null && fresh)
              Text(
                '${tr('Updated')}: ${stamp.toLocal().toString().split('.').first}',
              ),
            if (connection?['online'] == true)
              const AppText('PPPoE service online'),
            Align(
              alignment: AlignmentDirectional.centerStart,
              child: TextButton.icon(
                onPressed: refreshing || testing ? null : refresh,
                icon: const Icon(Icons.refresh),
                label: AppText(refreshing ? 'Refreshing…' : 'Refresh signal'),
              ),
            ),
            const Divider(height: 24),
            const AppText(
              'Check the connection on this device. Connect to your home Wi-Fi to test your home service; mobile data tests the mobile network.',
            ),
            const SizedBox(height: 12),
            Wrap(
              spacing: 12,
              runSpacing: 8,
              children: [
                OutlinedButton.icon(
                  onPressed: testing ? null : () => test(speed: false),
                  icon: const Icon(Icons.public),
                  label: const AppText('Check internet'),
                ),
                FilledButton.icon(
                  onPressed: testing ? null : () => test(speed: true),
                  icon: const Icon(Icons.speed),
                  label: const AppText('Start speed test'),
                ),
                if (testing)
                  TextButton(
                    onPressed: stop,
                    child: const AppText('Stop test'),
                  ),
              ],
            ),
            const SizedBox(height: 12),
            const AppText(
              'Tests connect to Cloudflare. A speed test uses up to 26 MB of test data. Results are estimates and depend on Wi-Fi and other traffic.',
            ),
            if (testing)
              const Padding(
                padding: EdgeInsets.symmetric(vertical: 12),
                child: LinearProgressIndicator(),
              ),
            if (testMessage != null)
              Padding(
                padding: const EdgeInsets.only(top: 12),
                child: AppText(testMessage!),
              ),
            if (speeds != null) ...[
              const SizedBox(height: 12),
              Text(
                '${tr('Download')}: ${speeds!['download_mbps']!.toStringAsFixed(1)} Mbps',
              ),
              Text(
                '${tr('Upload')}: ${speeds!['upload_mbps']!.toStringAsFixed(1)} Mbps',
              ),
              Text(
                '${tr('HTTP latency')}: ${speeds!['latency_ms']!.toStringAsFixed(0)} ms',
              ),
            ],
          ],
        ),
      ),
    );
  }
}
