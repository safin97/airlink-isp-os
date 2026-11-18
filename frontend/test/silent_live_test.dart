import 'dart:async';
import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:airlink_isp_os/api.dart';
import 'package:airlink_isp_os/main.dart';
import 'package:airlink_isp_os/ethernet_ports_dialog.dart';
import 'package:airlink_isp_os/sas4_user_details.dart';
import 'live_socket_fixture.dart';

void main() {
  testWidgets('silent live socket reconnects without a page refresh', (
    tester,
  ) async {
    final sockets = <FakeSocket>[];
    final api = Api(
      liveConnector: (uri, token) {
        final s = FakeSocket();
        sockets.add(s);
        return s;
      },
    )..token = 'token';
    api.startLive();
    await tester.pump(const Duration(seconds: 15));
    expect(sockets.single.closed, isTrue);
    await tester.pump(const Duration(seconds: 3));
    expect(sockets, hasLength(2));
    sockets.last.controller.add({'type': 'heartbeat'});
    await tester.pump();
    await tester.pump(const Duration(seconds: 10));
    expect(sockets.last.closed, isFalse);
    api.stopLive();
    await tester.pump();
    await tester.pump(const Duration(seconds: 20));
    expect(sockets, hasLength(2));
  });

  for (final role in ['owner', 'manager']) {
    testWidgets(
      '$role dashboard quietly falls back while sockets are unavailable',
      (tester) async {
        await tester.binding.setSurfaceSize(const Size(1440, 1000));
        addTearDown(() => tester.binding.setSurfaceSize(null));
        final identity = {
          'role': role,
          'username': role,
          'sections': ['dashboard', 'towers', 'monitoring', 'alerts'],
        };
        var reads = 0;
        final pending = Completer<http.Response>();
        final api =
            Api(
                client: MockClient((request) async {
                  if (request.url.path == '/api/auth/me') {
                    return http.Response(jsonEncode(identity), 200);
                  }
                  if (request.url.path == '/api/dashboard') {
                    reads++;
                    if (reads == 2) return pending.future;
                    return http.Response('{"system":{"cpu_percent":10}}', 200);
                  }
                  if (request.url.path == '/api/integrations/deye') {
                    return http.Response('{"configured":false}', 200);
                  }
                  return http.Response('[]', 200);
                }),
                liveConnector: (uri, token) => null,
              )
              ..token = 'token'
              ..user = identity;
        await tester.pumpWidget(
          MaterialApp(
            home: Operations(api: api, logout: () async {}),
          ),
        );
        await tester.pumpAndSettle();
        expect(find.text('10.0%'), findsOneWidget);
        await tester.pump(const Duration(seconds: 10));
        await tester.pump();
        expect(reads, 2);
        expect(find.text('10.0%'), findsOneWidget);
        expect(
          find.byWidgetPredicate(
            (w) => w is LinearProgressIndicator && w.value == null,
          ),
          findsNothing,
        );
        pending.complete(http.Response('{"system":{"cpu_percent":45}}', 200));
        await tester.pumpAndSettle();
        expect(find.text('45.0%'), findsOneWidget);
        expect(
          find.byWidgetPredicate(
            (w) => w is LinearProgressIndicator && w.value == null,
          ),
          findsNothing,
        );
        await tester.pumpWidget(const SizedBox());
      },
    );
  }

  testWidgets(
    'port polling retains readings without a spinner or overlapping requests',
    (tester) async {
      var calls = 0;
      final pending = Completer<http.Response>();
      final api = Api(
        client: MockClient((request) async {
          calls++;
          if (calls == 2) return pending.future;
          return http.Response(
            '{"supported":true,"snmp_status":"connected","ports":[{"name":"ether1","state":"connected","rx_bps":1000000}]}',
            200,
          );
        }),
      );
      await tester.pumpWidget(
        MaterialApp(
          home: EthernetPortsDialog(
            api: api,
            device: const {'id': '1', 'name': 'Router'},
          ),
        ),
      );
      await tester.pumpAndSettle();
      await tester.pump(const Duration(seconds: 5));
      expect(find.text('ether1'), findsOneWidget);
      expect(
        find.byWidgetPredicate(
          (w) => w is LinearProgressIndicator && w.value == null,
        ),
        findsNothing,
      );
      await tester.pump(const Duration(seconds: 5));
      expect(calls, 2);
      pending.complete(
        http.Response(
          '{"supported":true,"snmp_status":"connected","ports":[{"name":"ether1","state":"connected","rx_bps":2000000}]}',
          200,
        ),
      );
      await tester.pumpAndSettle();
      expect(find.text('2.000 Mbps'), findsOneWidget);
      await tester.pumpWidget(const SizedBox());
    },
  );

  testWidgets(
    'customer details update automatically and preserve an edit started in flight',
    (tester) async {
      var calls = 0;
      final pending = Completer<http.Response>();
      http.Response record(String name) => http.Response(
        jsonEncode({
          'id': 7,
          'username': 'customer',
          'fields': [
            {
              'key': 'firstname',
              'label': 'First name',
              'kind': 'text',
              'value': name,
              'editable': true,
            },
          ],
        }),
        200,
      );
      final api = Api(
        client: MockClient((request) async {
          calls++;
          if (calls == 3) return pending.future;
          return record(calls == 1 ? 'Original' : 'Updated');
        }),
      )..user = {'role': 'owner'};
      await tester.pumpWidget(
        MaterialApp(home: Sas4UserDetails(api: api, userId: 7)),
      );
      await tester.pumpAndSettle();
      await tester.pump(const Duration(seconds: 10));
      await tester.pumpAndSettle();
      expect(find.text('Updated'), findsOneWidget);
      await tester.pump(const Duration(seconds: 10));
      await tester.tap(find.text('Edit'));
      await tester.pumpAndSettle();
      await tester.enterText(
        find.widgetWithText(TextFormField, 'First name'),
        'My draft',
      );
      pending.complete(record('Remote change'));
      await tester.pumpAndSettle();
      expect(find.text('My draft'), findsOneWidget);
      await tester.pump(const Duration(seconds: 20));
      expect(calls, 3);
      expect(find.text('My draft'), findsOneWidget);
      await tester.pumpWidget(const SizedBox());
    },
  );
}
