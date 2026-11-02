import 'live_socket_fixture.dart';
import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:airlink_isp_os/api.dart';
import 'package:airlink_isp_os/live_socket_types.dart';
import 'package:airlink_isp_os/main.dart';

void main() {
  testWidgets(
    'live patches update performance without HTTP polling and reconnect safely',
    (tester) async {
      tester.view.physicalSize = const Size(1440, 1000);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final sockets = <FakeSocket>[];
      var requests = 0;
      final api =
          Api(
              client: MockClient((r) async {
                requests++;
                return http.Response(
                  jsonEncode(
                    r.url.path == '/api/dashboard'
                        ? {
                            'system': {'cpu_percent': 10},
                          }
                        : [],
                  ),
                  200,
                );
              }),
              liveConnector: (uri, token) {
                expect(uri.path, '/api/live');
                expect(uri.query, isEmpty);
                expect(token, 'session-token');
                final socket = FakeSocket();
                sockets.add(socket);
                return socket;
              },
            )
            ..token = 'session-token'
            ..user = {'role': 'owner', 'username': 'owner'};
      await tester.pumpWidget(
        MaterialApp(
          home: Operations(api: api, logout: () async {}),
        ),
      );
      await tester.pumpAndSettle();
      expect(find.text('10.0%'), findsOneWidget);
      final initial = requests;
      sockets.single.controller.add({
        'type': 'snapshot',
        'user': {'role': 'owner', 'username': 'owner'},
        'summary': {
          'system': {'cpu_percent': 15},
        },
        'rows': <String, dynamic>{},
      });
      await tester.pumpAndSettle();
      expect(find.text('15.0%'), findsOneWidget);
      sockets.single.controller.add({
        'type': 'patch',
        'summary': {
          'system': {'cpu_percent': 42},
        },
      });
      await tester.pumpAndSettle();
      expect(find.text('42.0%'), findsOneWidget);
      await tester.pump(const Duration(seconds: 31));
      expect(requests, initial);
      sockets.single.close();
      await tester.pump();
      await tester.pump(const Duration(seconds: 3));
      expect(sockets.length, 2);
      sockets.last.controller.add({
        'type': 'snapshot',
        'user': {'role': 'owner', 'username': 'owner'},
        'summary': {
          'system': {'cpu_percent': 23},
        },
        'rows': <String, dynamic>{},
      });
      await tester.pumpAndSettle();
      expect(find.text('23.0%'), findsOneWidget);
      await tester.pumpWidget(const SizedBox());
      expect(sockets.last.closed, isTrue);
      await tester.pump(const Duration(seconds: 10));
      expect(sockets.length, 2);
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets('expired live token refreshes before reconnecting', (
    tester,
  ) async {
    final sockets = <FakeSocket>[];
    final tokens = <String>[];
    final events = <Map<String, dynamic>>[];
    final refreshRequests = <String>[];
    final api = Api(
      client: MockClient((r) async {
        refreshRequests.add(r.url.path);
        return http.Response(
          jsonEncode({
            'access_token': 'renewed',
            'user': {'role': 'owner'},
          }),
          200,
        );
      }),
      liveConnector: (uri, token) {
        tokens.add(token);
        final socket = FakeSocket();
        sockets.add(socket);
        return socket;
      },
    )..token = 'old';
    final subscription = api.liveEvents.listen(events.add);
    addTearDown(subscription.cancel);
    addTearDown(api.stopLive);
    api.startLive();
    sockets.single.controller.addError(LiveAuthenticationExpired());
    await tester.pumpAndSettle();
    expect(
      api.token,
      'renewed',
      reason: 'requests=$refreshRequests events=$events',
    );
    await tester.pump(const Duration(seconds: 3));
    expect(tokens, ['old', 'renewed']);
    expect(refreshRequests, ['/api/auth/refresh']);
    api.stopLive();
    await tester.pump();
  });
}
