import 'dart:async';
import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:airlink_isp_os/api.dart';
import 'package:airlink_isp_os/device_downtime_history.dart';

void main() {
  testWidgets(
    'Recovery history refreshes with start, end and duration; failed reads clear old data',
    (tester) async {
      var calls = 0;
      final api = Api(
        client: MockClient((request) async {
          expect(request.url.path, '/api/devices/1/outages');
          expect(request.url.queryParameters['limit'], '100');
          calls++;
          if (calls == 3) {
            return http.Response('{"detail":"Access denied"}', 403);
          }
          return http.Response(
            jsonEncode(
              calls == 1
                  ? []
                  : [
                      {
                        'started_at': '2026-11-09T10:00:00Z',
                        'ended_at': '2026-11-09T12:01:00Z',
                        'duration_seconds': 7260,
                      },
                    ],
            ),
            200,
          );
        }),
      );
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: DeviceDowntimeHistory(api: api, deviceId: '1'),
          ),
        ),
      );
      await tester.pumpAndSettle();
      expect(find.text('No completed outages recorded yet.'), findsOneWidget);
      await tester.pump(const Duration(seconds: 15));
      await tester.pumpAndSettle();
      expect(find.text('Offline since'), findsOneWidget);
      expect(find.text('Back online'), findsOneWidget);
      expect(find.text('0d 2h 1m 0s'), findsOneWidget);
      final row = tester.widget<DataTable>(find.byType(DataTable)).rows.single;
      expect(row.cells[0].child, isA<Text>());
      expect((row.cells[0].child as Text).data, contains('2026-11-09'));
      await tester.tap(find.byTooltip('Refresh downtime history'));
      await tester.pumpAndSettle();
      expect(find.textContaining('Access denied'), findsOneWidget);
      expect(find.text('0d 2h 1m 0s'), findsNothing);
      await tester.pumpWidget(const SizedBox());
    },
  );

  testWidgets(
    'Switching devices ignores a delayed response for the previous device',
    (tester) async {
      final old = Completer<http.Response>();
      final api = Api(
        client: MockClient((request) async {
          if (request.url.path == '/api/devices/old/outages') return old.future;
          return http.Response('[]', 200);
        }),
      );
      Widget view(String id) => MaterialApp(
        home: Scaffold(
          body: DeviceDowntimeHistory(api: api, deviceId: id),
        ),
      );
      await tester.pumpWidget(view('old'));
      await tester.pump();
      await tester.pumpWidget(view('new'));
      await tester.pumpAndSettle();
      old.complete(http.Response('[{"duration_seconds":7200}]', 200));
      await tester.pumpAndSettle();
      expect(find.text('No completed outages recorded yet.'), findsOneWidget);
      expect(find.byType(DataTable), findsNothing);
      await tester.pumpWidget(const SizedBox());
    },
  );
}
