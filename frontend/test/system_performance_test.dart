import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:airlink_isp_os/system_performance.dart';

void main() {
  testWidgets(
    'PC performance shows only CPU, memory, storage and disk activity',
    (tester) async {
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
                  'gpus': [
                    {
                      'name': 'NVIDIA RTX',
                      'utilization_percent': 0,
                      'memory_used_mib': 256,
                      'memory_total_mib': 8192,
                      'temperature_c': 42,
                    },
                  ],
                  'network': [
                    {
                      'name': 'eth0',
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
      expect(find.text('24.5%'), findsOneWidget);
      expect(find.byType(Card), findsNWidgets(4));
      for (final title in ['CPU', 'Memory', 'Storage', 'Disk activity']) {
        expect(find.text(title), findsOneWidget);
      }
      expect(find.text('100.00 Mbps'), findsNothing);
      expect(find.text('1.00 MiB/s'), findsOneWidget);
      expect(find.text('NVIDIA RTX'), findsNothing);
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
    },
  );
}
