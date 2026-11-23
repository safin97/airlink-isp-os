import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:airlink_isp_os/api.dart';
import 'package:airlink_isp_os/client_portal.dart';

void main() {
  for (final shared in [false, true]) {
    for (final accepted in [true, false]) {
      testWidgets(
        'phone login uses the configured mode: shared=$shared accepted=$accepted',
        (tester) async {
          tester.view.physicalSize = const Size(390, 844);
          tester.view.devicePixelRatio = 1;
          addTearDown(tester.view.resetPhysicalSize);
          addTearDown(tester.view.resetDevicePixelRatio);
          var authenticated = false, challenges = 0;
          Map<String, dynamic>? submitted;
          final api = Api(
            client: MockClient((request) async {
              switch (request.url.path) {
                case '/api/client/account':
                  return authenticated
                      ? http.Response(
                          jsonEncode({
                            'username': 'verified-subscriber',
                            'phone': '07500000000',
                            'profile': 'AirLink Basic',
                            'expiration': null,
                            'payments': [],
                            'can_recharge': true,
                            'fib_configured': false,
                          }),
                          200,
                        )
                      : http.Response('{"detail":"Sign in"}', 401);
                case '/api/client/connection-check':
                  return http.Response(
                    '{"source_ip":"127.0.0.1","auto_login_eligible":false}',
                    200,
                  );
                case '/api/client/auto-login':
                  return http.Response('{"authenticated":false}', 200);
                case '/api/client/login-options':
                  challenges++;
                  return http.Response(
                    jsonEncode({
                      'challenge_id': 'phone-challenge',
                      'captcha_image': null,
                      'shared_phone_password': shared,
                      'prefill_phone_password': shared,
                    }),
                    200,
                  );
                case '/api/client/login':
                  submitted = jsonDecode(request.body);
                  authenticated = accepted;
                  return accepted
                      ? http.Response('{"authenticated":true}', 200)
                      : http.Response(
                          '{"detail":"Invalid phone number, username, password or verification code."}',
                          401,
                        );
                default:
                  throw StateError('Unexpected request ${request.url.path}');
              }
            }),
          );
          await tester.pumpWidget(MaterialApp(home: ClientPortal(api: api)));
          await tester.pumpAndSettle();
          expect(find.text('Phone number'), findsOneWidget);
          expect(find.byType(TextField), findsNWidgets(shared ? 1 : 2));
          if (shared) {
            expect(find.text('Password'), findsNothing);
            expect(find.text('Use username instead'), findsNothing);
            expect(
              find.text('Check IP and sign in automatically'),
              findsNothing,
            );
            expect(
              find.textContaining('Connection IP seen by AirLink'),
              findsNothing,
            );
            expect(find.byType(TextButton), findsNothing);
          } else {
            expect(
              tester
                  .widget<TextField>(find.byType(TextField).at(1))
                  .controller!
                  .text,
              isEmpty,
            );
          }
          await tester.enterText(find.byType(TextField).at(0), '07500000000');
          if (!shared) {
            await tester.enterText(
              find.byType(TextField).at(1),
              'my-existing-sas4-password',
            );
          }
          await tester.ensureVisible(find.text('Sign in'));
          await tester.pumpAndSettle();
          await tester.tap(find.text('Sign in'));
          await tester.pumpAndSettle();
          expect(submitted, {
            'phone': '07500000000',
            'password': shared ? '123' : 'my-existing-sas4-password',
            'challenge_id': 'phone-challenge',
            'captcha_text': '',
          });
          if (accepted) {
            expect(find.byType(NavigationDestination), findsNWidgets(5));
            expect(find.textContaining('verified-subscriber'), findsWidgets);
          } else {
            expect(find.byType(NavigationDestination), findsNothing);
            expect(
              find.text(
                'Invalid phone number, username, password or verification code.',
              ),
              findsOneWidget,
            );
            expect(find.byType(TextField), findsNWidgets(shared ? 1 : 2));
            if (!shared) {
              expect(
                tester
                    .widget<TextField>(find.byType(TextField).at(1))
                    .controller!
                    .text,
                isEmpty,
              );
            }
            expect(challenges, 2);
          }
          expect(tester.takeException(), isNull);
          await tester.pumpWidget(const SizedBox.shrink());
        },
      );
    }
  }
}
