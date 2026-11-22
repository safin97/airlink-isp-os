import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:airlink_isp_os/api.dart';
import 'package:airlink_isp_os/client_portal.dart';

void main() {
  for (final failure in [
    'outside_subscriber_ranges',
    'stale_session',
    'server_error',
  ]) {
    testWidgets('manual login remains usable after $failure', (tester) async {
      var authenticated = false, signedIn = 0;
      final api = Api(
        client: MockClient((request) async {
          switch (request.url.path) {
            case '/api/client/account':
              return authenticated
                  ? http.Response(
                      jsonEncode({
                        'username': 'subscriber',
                        'profile': 'AirLink Basic',
                        'expiration': null,
                        'payments': [],
                        'can_recharge': true,
                        'fib_configured': false,
                      }),
                      200,
                    )
                  : http.Response('{"detail":"Sign in"}', 401);
            case '/api/client/auto-login':
              return failure == 'server_error'
                  ? http.Response(
                      '{"detail":"Automatic service unavailable"}',
                      503,
                    )
                  : http.Response(
                      jsonEncode({
                        'authenticated': false,
                        'reason': failure,
                        'source_ip': '172.20.5.10',
                      }),
                      200,
                    );
            case '/api/client/login-options':
              return http.Response(
                '{"challenge_id":"test-challenge","captcha_image":null}',
                200,
              );
            case '/api/client/login':
              expect(jsonDecode(request.body)['username'], 'subscriber');
              expect(jsonDecode(request.body)['password'], 'test-password');
              authenticated = true;
              signedIn++;
              return http.Response('{"authenticated":true}', 200);
            default:
              throw StateError('Unexpected request: ${request.url.path}');
          }
        }),
      );
      await tester.pumpWidget(MaterialApp(home: ClientPortal(api: api)));
      await tester.pumpAndSettle();
      expect(find.text('Sign in'), findsOneWidget);
      expect(find.byType(TextField), findsNWidgets(2));
      if (failure == 'outside_subscriber_ranges') {
        expect(
          find.textContaining('outside the automatic-login ranges'),
          findsOneWidget,
        );
      }
      if (failure == 'stale_session') {
        expect(
          find.textContaining('more than two minutes old'),
          findsOneWidget,
        );
      }
      if (failure == 'server_error') {
        expect(find.textContaining('could not be verified'), findsOneWidget);
      }
      if (failure != 'server_error') {
        expect(find.textContaining('172.20.5.10'), findsOneWidget);
      }
      await tester.enterText(find.byType(TextField).at(0), 'subscriber');
      await tester.enterText(find.byType(TextField).at(1), 'test-password');
      await tester.ensureVisible(find.text('Sign in'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Sign in'));
      await tester.pumpAndSettle();
      expect(signedIn, 1);
      expect(find.byType(NavigationDestination), findsNWidgets(5));
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox.shrink());
    });
  }
}
