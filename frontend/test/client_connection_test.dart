import 'dart:convert';
import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:airlink_isp_os/api.dart';
import 'package:airlink_isp_os/client_connection.dart';
import 'package:airlink_isp_os/client_speed_test.dart';

class FakeSpeedTest extends ClientSpeedTest {
  final bool fail;
  FakeSpeedTest({this.fail = false});
  @override
  Future<double> checkInternet() async {
    if (fail) throw StateError('Network unavailable');
    return 25;
  }

  @override
  Future<Map<String, double>> run(void Function(String) progress) async => {
    'latency_ms': 25,
    'download_mbps': 42.5,
    'upload_mbps': 12.3,
  };
}

class PendingSpeedTest extends ClientSpeedTest {
  final result = Completer<Map<String, double>>();
  @override
  Future<Map<String, double>> run(void Function(String) progress) =>
      result.future;
}

void main() {
  testWidgets('stopping a test discards its late result', (tester) async {
    tester.view.physicalSize = const Size(480, 1400);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final runner = PendingSpeedTest();
    final api = Api(
      client: MockClient(
        (_) async => http.Response('{"status":"unavailable"}', 200),
      ),
    );
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: ClientConnection(api: api, testFactory: () => runner),
        ),
      ),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.text('Start speed test'));
    await tester.pump();
    await tester.tap(find.text('Stop test'));
    await tester.pumpAndSettle();
    expect(runner.stopped, true);
    runner.result.complete({
      'download_mbps': 99,
      'upload_mbps': 99,
      'latency_ms': 1,
    });
    await tester.pumpAndSettle();
    expect(find.text('Test stopped.'), findsOneWidget);
    expect(find.textContaining('Download:'), findsNothing);
    await tester.pumpWidget(const SizedBox.shrink());
  });
  testWidgets(
    'signal and explicit browser checks have separate truthful results',
    (tester) async {
      tester.view.physicalSize = const Size(480, 1400);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      int started = 0;
      bool fail = false, stale = false;
      final api = Api(
        client: MockClient((request) async {
          expect(request.url.path, '/api/client/connection');
          return http.Response(
            jsonEncode({
              'online': true,
              'signal_dbm': -62,
              'status': 'available',
              'collected_at': DateTime.now()
                  .subtract(Duration(minutes: stale ? 5 : 0))
                  .toIso8601String(),
            }),
            200,
          );
        }),
      );
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: ClientConnection(
              api: api,
              testFactory: () {
                started++;
                return FakeSpeedTest(fail: fail);
              },
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(find.text('Wireless signal: -62 dBm'), findsOneWidget);
      expect(started, 0);
      await tester.tap(find.text('Check internet'));
      await tester.pumpAndSettle();
      expect(find.textContaining('Internet reachable'), findsOneWidget);
      await tester.tap(find.text('Start speed test'));
      await tester.pumpAndSettle();
      expect(find.text('Download: 42.5 Mbps'), findsOneWidget);
      expect(find.text('Upload: 12.3 Mbps'), findsOneWidget);
      fail = true;
      await tester.tap(find.text('Check internet'));
      await tester.pumpAndSettle();
      expect(
        find.textContaining('Could not reach the test server'),
        findsOneWidget,
      );
      expect(find.textContaining('Download:'), findsNothing);
      stale = true;
      await tester.tap(find.text('Refresh signal'));
      await tester.pumpAndSettle();
      expect(find.text('Wireless signal: —'), findsOneWidget);
      await tester.pumpWidget(const SizedBox.shrink());
    },
  );
}
