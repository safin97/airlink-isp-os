import 'package:airlink_isp_os/deye_energy_overview.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  for (final width in [360.0, 1440.0]) {
    testWidgets(
      'Grid downtime updates without counting unknown readings at $width',
      (tester) async {
        await tester.binding.setSurfaceSize(Size(width, 1200));
        addTearDown(() => tester.binding.setSurfaceSize(null));
        var state = 'down';
        num? current = 61;
        Future<void> show() async {
          await tester.pumpWidget(
            MaterialApp(
              home: Scaffold(
                body: SingleChildScrollView(
                  child: DeyeEnergyOverview(
                    compact: true,
                    reading: {
                      'grid_availability': {
                        'state': state,
                        'started_at': '2026-11-17T01:00:00Z',
                        'uptime_seconds': 7200,
                        'downtime_seconds': 3661,
                        'unknown_seconds': 90,
                        'current_outage_seconds': current,
                      },
                    },
                  ),
                ),
              ),
            ),
          );
          await tester.pump(const Duration(milliseconds: 200));
        }

        await show();
        expect(find.text('Grid downtime'), findsOneWidget);
        expect(find.text('Current outage: 0h 1m 1s'), findsOneWidget);
        expect(find.text('Observed downtime: 1h 1m 1s'), findsOneWidget);
        expect(find.text('Unknown time: 0h 1m 30s'), findsOneWidget);
        expect(find.textContaining('Totals since'), findsOneWidget);
        expect(tester.takeException(), isNull);
        state = 'unknown';
        current = null;
        await show();
        expect(find.text('Current outage: Unknown'), findsOneWidget);
        expect(find.text('Observed downtime: 1h 1m 1s'), findsOneWidget);
        state = 'up';
        current = 0;
        await show();
        expect(find.text('Current outage: None'), findsOneWidget);
        expect(tester.takeException(), isNull);
        await tester.pumpWidget(const SizedBox());
      },
    );
  }
}
