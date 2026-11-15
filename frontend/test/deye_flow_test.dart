import 'package:airlink_isp_os/deye_energy_overview.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  testWidgets(
    'energy keeps moving between cloud samples and follows charging direction',
    (tester) async {
      final semantics = tester.ensureSemantics();

      var reducedMotion = false, active = true;
      var reading = <String, dynamic>{
        'freshness': 'recent',
        'observed_at': '2026-11-15T13:43:25Z',
        'solar_w': 57,
        'load_w': 1952,
        'charge_w': 4976,
        'discharge_w': 0,
        'import_w': 7163,
        'export_w': 0,
        'grid_availability': {'state': 'up'},
      };
      Widget view() => MaterialApp(
        home: MediaQuery(
          data: MediaQueryData(disableAnimations: reducedMotion),
          child: TickerMode(
            enabled: active,
            child: Scaffold(
              body: DeyeEnergyOverview(reading: reading, compact: true),
            ),
          ),
        ),
      );
      await tester.pumpWidget(view());
      expect(
        find.bySemanticsLabel(
          RegExp(
            'Energy flow:.*Solar to inverter.*Inverter to battery.*Grid to inverter.*Inverter to load',
          ),
        ),
        findsOneWidget,
      );
      for (var i = 0; i < 4; i++) {
        await tester.pump(const Duration(milliseconds: 1500));
        expect(tester.binding.hasScheduledFrame, isTrue);
      }
      reading = {...reading, 'charge_w': 0, 'discharge_w': 2200};
      await tester.pumpWidget(view());
      expect(
        find.bySemanticsLabel(RegExp('Energy flow:.*Battery to inverter')),
        findsOneWidget,
      );
      expect(
        find.bySemanticsLabel(RegExp('Energy flow:.*Inverter to battery')),
        findsNothing,
      );
      reducedMotion = true;
      await tester.pumpWidget(view());
      await tester.pumpAndSettle();
      expect(tester.binding.hasScheduledFrame, isFalse);
      reducedMotion = false;
      active = false;
      await tester.pumpWidget(view());
      await tester.pumpAndSettle();
      expect(tester.binding.hasScheduledFrame, isFalse);
      active = true;
      reading = {...reading, 'freshness': 'stale'};
      await tester.pumpWidget(view());
      await tester.pumpAndSettle();
      expect(
        find.bySemanticsLabel(RegExp('^No confirmed energy flow')),
        findsOneWidget,
      );
      expect(tester.binding.hasScheduledFrame, isFalse);
      reading = {
        ...reading,
        'freshness': 'recent',
        'solar_w': 0,
        'load_w': 0,
        'charge_w': 0,
        'discharge_w': 0,
        'import_w': 0,
        'export_w': 0,
      };
      await tester.pumpWidget(view());
      await tester.pumpAndSettle();
      expect(
        find.bySemanticsLabel(RegExp('^No confirmed energy flow')),
        findsOneWidget,
      );
      expect(tester.binding.hasScheduledFrame, isFalse);
      await tester.pumpWidget(const SizedBox());
      semantics.dispose();
    },
  );
}
