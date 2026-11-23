import 'dart:async';
import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:airlink_isp_os/api.dart';
import 'package:airlink_isp_os/client_portal.dart';
import 'package:airlink_isp_os/client_dashboard.dart';
import 'package:airlink_isp_os/client_dashboard_style.dart';
import 'package:airlink_isp_os/client_speed_gauge.dart';
import 'package:airlink_isp_os/client_speed_test.dart';

class MeasuredTest extends ClientSpeedTest {
  final completion = Completer<Map<String, double>>();
  @override
  Future<Map<String, double>> run(void Function(String) progress) {
    progress('Testing download…');
    onMeasurement?.call('download_mbps', 42.5);
    return completion.future;
  }
}

void main() {
  test('SAS4 expiry honors explicit offsets and Iraq timestamps', () {
    expect(
      clientSubscriptionExpiry('2026-12-01 03:00:00'),
      DateTime.utc(2026, 12, 1),
    );
    expect(
      clientSubscriptionExpiry('2026-12-01T00:00:00Z'),
      DateTime.utc(2026, 12, 1),
    );
    expect(clientSubscriptionExpiry(null), isNull);
    expect(clientSubscriptionExpiry('not a date'), isNull);
  });

  for (final size in [
    const Size(320, 812),
    const Size(390, 844),
    const Size(1280, 900),
  ]) {
    testWidgets('authenticated dashboard refreshes expiry and fits $size', (
      tester,
    ) async {
      tester.view.physicalSize = size;
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      var expired = false;
      var reads = 0;
      final api = Api(
        client: MockClient((request) async {
          expect(request.method, 'GET');
          expect(request.url.path, '/api/client/account');
          reads++;
          return http.Response(
            jsonEncode({
              'username': 'customer-with-a-long-username',
              'profile': 'AirLink Plus',
              'expiration': DateTime.now()
                  .add(Duration(days: expired ? -1 : 10))
                  .toUtc()
                  .toIso8601String(),
              'recharge_cost': '25000',
              'currency': 'IQD',
              'payments': [],
              'can_recharge': true,
              'fib_configured': true,
            }),
            200,
          );
        }),
      );
      await tester.pumpWidget(MaterialApp(home: ClientPortal(api: api)));
      await tester.pumpAndSettle();
      expect(find.text('Active'), findsOneWidget);
      expect(find.byType(NavigationDestination), findsNWidgets(5));
      expect(find.byType(ClientSpeedGauge), findsNothing);
      expect(find.text('Internet speed'), findsNothing);
      expired = true;
      await tester.tap(find.byTooltip('Refresh account'));
      await tester.pumpAndSettle();
      expect(reads, 2);
      expect(find.text('Active'), findsNothing);
      expect(find.text('Expired'), findsNWidgets(2));
      await tester.ensureVisible(find.text('Recharge now'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Recharge now'));
      await tester.pumpAndSettle();
      expect(find.text('Recharge PIN').hitTestable(), findsOneWidget);
      expect(find.text('FIB Bank').hitTestable(), findsOneWidget);
      await tester.tap(find.byTooltip('Notifications'));
      await tester.pumpAndSettle();
      expect(find.text('Account notifications'), findsOneWidget);
      expect(find.text('No recent payment updates.'), findsOneWidget);
      Navigator.of(tester.element(find.text('Account notifications'))).pop();
      await tester.pumpAndSettle();
      await tester.tap(find.byType(NavigationDestination).at(3));
      await tester.pumpAndSettle();
      expect(find.text('NOC Center'), findsOneWidget);
      expect(find.text('07501033002'), findsOneWidget);
      expect(find.text('07501033004'), findsOneWidget);
      expect(find.text('Quick help'), findsNothing);
      expect(find.text('Helpful answers'), findsNothing);
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox.shrink());
    });
  }

  testWidgets('speedometer shows measurements and discards a stopped result', (
    tester,
  ) async {
    final runner = MeasuredTest();
    await tester.pumpWidget(
      MaterialApp(
        theme: clientDashboardTheme(),
        home: Scaffold(
          body: SingleChildScrollView(
            child: ClientSpeedGauge(testFactory: () => runner),
          ),
        ),
      ),
    );
    expect(find.text('42.5'), findsNothing);
    await tester.ensureVisible(find.text('Start speed test'));
    await tester.tap(find.text('Start speed test'));
    await tester.pump(const Duration(seconds: 1));
    expect(find.text('42.5'), findsWidgets);
    await tester.tap(find.text('Stop test'));
    await tester.pumpAndSettle();
    runner.completion.complete({
      'download_mbps': 88,
      'upload_mbps': 12,
      'latency_ms': 30,
      'jitter_ms': 2,
    });
    await tester.pumpAndSettle();
    expect(find.text('88.0'), findsNothing);
    expect(find.text('Test stopped.'), findsOneWidget);
    expect(runner.stopped, true);
    await tester.pumpWidget(const SizedBox.shrink());
  });
}
