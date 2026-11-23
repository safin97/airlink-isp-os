import 'dart:async';
import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:airlink_isp_os/api.dart';
import 'package:airlink_isp_os/client_portal.dart';

http.Response account() => http.Response(
  jsonEncode({
    'username': 'verified-subscriber',
    'profile': 'AirLink Basic',
    'expiration': null,
    'payments': [],
    'can_recharge': true,
    'fib_configured': false,
  }),
  200,
);

void main() {
  testWidgets(
    'checks connection before matching SAS4 and opens the verified account',
    (tester) async {
      final check = Completer<http.Response>();
      final identify = Completer<http.Response>();
      final paths = <String>[];
      var authenticated = false;
      final api = Api(
        client: MockClient((request) async {
          paths.add(request.url.path);
          switch (request.url.path) {
            case '/api/client/account':
              return authenticated
                  ? account()
                  : http.Response('{"detail":"Sign in"}', 401);
            case '/api/client/connection-check':
              return check.future;
            case '/api/client/auto-login':
              final result = await identify.future;
              authenticated = true;
              return result;
            default:
              throw StateError('Unexpected request ${request.url.path}');
          }
        }),
      );
      await tester.pumpWidget(MaterialApp(home: ClientPortal(api: api)));
      await tester.pump();
      await tester.pump();
      expect(find.text('Checking your connection IP…'), findsOneWidget);
      expect(paths, ['/api/client/account', '/api/client/connection-check']);
      check.complete(
        http.Response(
          '{"source_ip":"172.19.3.10","internet_ip":null,"auto_login_eligible":true}',
          200,
        ),
      );
      await tester.pump();
      await tester.pump();
      expect(find.text('Identifying your AirLink account…'), findsOneWidget);
      expect(find.textContaining('172.19.3.10'), findsOneWidget);
      expect(find.byType(NavigationDestination), findsNothing);
      identify.complete(http.Response('{"authenticated":true}', 200));
      await tester.pumpAndSettle();
      expect(paths, [
        '/api/client/account',
        '/api/client/connection-check',
        '/api/client/auto-login',
        '/api/client/account',
      ]);
      expect(find.textContaining('verified-subscriber'), findsWidgets);
      expect(find.byType(NavigationDestination), findsNWidgets(5));
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox.shrink());
    },
  );

  testWidgets(
    'public IP never fills credentials or authenticates; explicit retry checks again',
    (tester) async {
      tester.view.physicalSize = const Size(390, 844);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      var checks = 0, matches = 0;
      final api = Api(
        client: MockClient((request) async {
          switch (request.url.path) {
            case '/api/client/account':
              return http.Response('{"detail":"Sign in"}', 401);
            case '/api/client/connection-check':
              checks++;
              return http.Response(
                '{"source_ip":"127.0.0.1","internet_ip":"8.8.8.8","internet_ip_source":"cloudflare","auto_login_eligible":false}',
                200,
              );
            case '/api/client/auto-login':
              matches++;
              expect(request.body, isNot(contains('8.8.8.8')));
              return http.Response(
                '{"authenticated":false,"source_ip":"127.0.0.1","reason":"local_connection"}',
                200,
              );
            case '/api/client/login-options':
              return http.Response(
                '{"challenge_id":"challenge","captcha_image":null}',
                200,
              );
            default:
              throw StateError('Unexpected request ${request.url.path}');
          }
        }),
      );
      await tester.pumpWidget(MaterialApp(home: ClientPortal(api: api)));
      await tester.pumpAndSettle();
      expect(
        find.textContaining('Public internet IP: 8.8.8.8'),
        findsOneWidget,
      );
      expect(find.textContaining('not used as proof'), findsOneWidget);
      expect(find.byType(NavigationDestination), findsNothing);
      for (final field in tester.widgetList<TextField>(
        find.byType(TextField),
      )) {
        expect(field.controller!.text, isEmpty);
      }
      final retry = find.text('Check IP and sign in automatically');
      await tester.ensureVisible(retry);
      await tester.pumpAndSettle();
      await tester.tap(retry);
      await tester.pumpAndSettle();
      expect(checks, 2);
      expect(matches, 2);
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox.shrink());
    },
  );

  testWidgets(
    'remembered customer session opens without new IP identification',
    (tester) async {
      final paths = <String>[];
      final api = Api(
        client: MockClient((request) async {
          paths.add(request.url.path);
          expect(request.url.path, '/api/client/account');
          return account();
        }),
      );
      await tester.pumpWidget(MaterialApp(home: ClientPortal(api: api)));
      await tester.pumpAndSettle();
      expect(paths, ['/api/client/account']);
      expect(find.byType(NavigationDestination), findsNWidgets(5));
      await tester.pumpWidget(const SizedBox.shrink());
    },
  );
}
