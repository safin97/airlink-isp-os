import 'package:airlink_isp_os/deye_energy_overview.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  for (final compact in [true, false]) {
    for (final width in [360.0, 1440.0]) {
      testWidgets('load watts and amps at $width compact=$compact', (
        tester,
      ) async {
        await tester.binding.setSurfaceSize(Size(width, 1600));
        addTearDown(() => tester.binding.setSurfaceSize(null));
        var reading = <String, dynamic>{
          'load_w': 1800,
          'load_current': {
            'current_a': 8.03,
            'source': 'estimated',
            'voltage_v': 224.2,
          },
        };
        Widget view() => MaterialApp(
          home: Scaffold(
            body: SingleChildScrollView(
              child: DeyeEnergyOverview(reading: reading, compact: compact),
            ),
          ),
        );
        await tester.pumpWidget(view());
        expect(find.text('1800 W'), findsOneWidget);
        expect(find.text('Est. 8.0 A'), findsOneWidget);
        expect(
          find.byWidgetPredicate(
            (w) => w is Tooltip && (w.message ?? '').contains('power factor 1'),
          ),
          findsOneWidget,
        );
        expect(tester.takeException(), isNull);
        reading = {
          ...reading,
          'load_w': 798,
          'load_current': {'current_a': 4.2, 'source': 'measured'},
        };
        await tester.pumpWidget(view());
        expect(find.text('798 W'), findsOneWidget);
        expect(find.text('4.2 A'), findsOneWidget);
        expect(find.text('Est. 8.0 A'), findsNothing);
        reading = {...reading, 'load_current': null};
        await tester.pumpWidget(view());
        expect(find.text('Amps unavailable'), findsOneWidget);
        expect(find.text('0.0 A'), findsNothing);
        reading = {
          ...reading,
          'load_w': 0,
          'load_current': {'current_a': 0, 'source': 'measured'},
        };
        await tester.pumpWidget(view());
        expect(find.text('0 W'), findsOneWidget);
        expect(find.text('0.0 A'), findsOneWidget);
        expect(tester.takeException(), isNull);
      });
    }
  }
}
