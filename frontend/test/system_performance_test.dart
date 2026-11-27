import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:airlink_isp_os/system_performance.dart';

void main() {
  testWidgets('PC performance includes latency without network traffic cards', (
    tester,
  ) async {
    await tester.pumpWidget(
      const MaterialApp(
        home: Scaffold(
          body: SingleChildScrollView(
            child: SystemPerformance(
              data: {
                'status': 'ready',
                'hostname': 'AirLink PC',
                'platform': 'Linux',
                'cpu_percent': 24.5,
                'cpu_mhz': 3200,
                'cpu_cores': 4,
                'cpu_threads': 8,
                'memory': {
                  'percent': 50,
                  'used_bytes': 4294967296,
                  'total_bytes': 8589934592,
                  'available_bytes': 4294967296,
                },
                'latency': {
                  'google_dns': {'status': 'ready', 'rtt_ms': 12.4},
                  'gaming': {'status': 'no_reply', 'rtt_ms': null},
                },
                'gpus': [
                  {
                    'name': 'NVIDIA RTX',
                    'status': 'ready',
                    'driver': 'nvidia',
                    'driver_version': '610',
                    'utilization_percent': 0,
                    'memory_used_mib': 256,
                    'memory_total_mib': 8192,
                    'temperature_c': 42,
                  },
                ],
                'network': [
                  {
                    'name': 'eth0',
                    'kind': 'ethernet',
                    'is_up': true,
                    'rx_bytes_sec': 12500000,
                    'tx_bytes_sec': 125000,
                    'link_mbps': 1000,
                  },
                ],
                'disk_read_bytes_sec': 1048576,
                'disk_write_bytes_sec': 2097152,
              },
            ),
          ),
        ),
      ),
    );
    expect(find.text('PC performance'), findsOneWidget);
    expect(find.text('System TX & RX'), findsNothing);
    expect(find.text('Ethernet · eth0'), findsNothing);
    expect(find.text('24.5%'), findsOneWidget);
    expect(find.byType(Card), findsNWidgets(7));
    for (final title in ['CPU', 'Memory', 'Storage', 'Disk activity']) {
      expect(find.text(title), findsOneWidget);
    }
    expect(find.text('TX 1.00 Mbps\nRX 100.00 Mbps'), findsNothing);
    expect(find.text('12.4 ms'), findsOneWidget);
    expect(find.text('No reply'), findsOneWidget);
    expect(find.text('Not actual PUBG / Call of Duty ping'), findsOneWidget);
    expect(find.text('1.00 MiB/s'), findsOneWidget);
    expect(find.text('NVIDIA RTX'), findsOneWidget);
    expect(find.text('0.0%'), findsOneWidget);
    expect(find.text('Temperature: 42.0 °C'), findsOneWidget);
    expect(find.text('Driver: nvidia · 610'), findsOneWidget);
    expect(tester.takeException(), isNull);
    await tester.pumpWidget(
      const MaterialApp(
        home: Scaffold(
          body: SingleChildScrollView(child: SystemPerformance(data: {})),
        ),
      ),
    );
    expect(find.text('Unavailable'), findsWidgets);
    expect(find.text('0.0%'), findsNothing);
    expect(tester.takeException(), isNull);
  });
  testWidgets(
    'GPU follows CPU and updates active, idle and unavailable states',
    (tester) async {
      Future<void> show(String state, dynamic usage) async {
        await tester.pumpWidget(
          MaterialApp(
            home: Scaffold(
              body: SingleChildScrollView(
                child: SystemPerformance(
                  data: {
                    'gpus': [
                      {
                        'name': 'NVIDIA GeForce GTX 1660 Ti',
                        'status': state,
                        'driver': state == 'not_loaded' ? null : 'nvidia',
                        'utilization_percent': usage,
                      },
                    ],
                  },
                ),
              ),
            ),
          ),
        );
      }

      await show('ready', 64);
      final gpuCard = find.ancestor(
        of: find.text('NVIDIA GeForce GTX 1660 Ti'),
        matching: find.byType(Card),
      );
      final bar = find.descendant(
        of: gpuCard,
        matching: find.byType(LinearProgressIndicator),
      );
      expect(find.text('Working · Active'), findsOneWidget);
      expect(find.text('64.0%'), findsOneWidget);
      expect(tester.widget<LinearProgressIndicator>(bar).value, 0.64);
      final cards = tester.widgetList<Card>(find.byType(Card)).toList();
      expect(cards[1], tester.widget<Card>(gpuCard));

      await show('ready', 0);
      expect(find.text('Working · Idle'), findsOneWidget);
      expect(find.text('Working · Active'), findsNothing);
      expect(tester.widget<LinearProgressIndicator>(bar).value, 0);

      for (final usage in [null, -1, 101, double.nan, double.infinity, '25']) {
        await show('ready', usage);
        expect(find.text('Usage unavailable'), findsOneWidget);
        expect(find.text('Working · Idle'), findsNothing);
        expect(bar, findsNothing);
      }
      await show('loaded', 64);
      expect(find.text('GPU detected; telemetry unavailable'), findsOneWidget);
      expect(find.text('64.0%'), findsNothing);
      expect(bar, findsNothing);
      await show('not_loaded', 64);
      expect(find.text('Driver not loaded'), findsOneWidget);
      expect(find.text('GPU detected; driver not loaded'), findsOneWidget);
      expect(bar, findsNothing);
      expect(tester.takeException(), isNull);
    },
  );
}
