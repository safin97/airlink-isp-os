import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:url_launcher/link.dart';
import 'package:airlink_isp_os/api.dart';
import 'package:airlink_isp_os/client_portal.dart';

void main() {
  for (final automatic in [false, true]) {
    testWidgets(
      '${automatic ? 'Network' : 'Password'} login recharges only the signed-in customer',
      (tester) async {
        tester.view.physicalSize = const Size(390, 844);
        tester.view.devicePixelRatio = 1;
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);
        bool authenticated = false;
        final requests = <http.Request>[];
        final api = Api(
          client: MockClient((request) async {
            requests.add(request);
            expect(request.url.path, startsWith('/api/client/'));
            Object result;
            switch (request.url.path) {
              case '/api/client/connection':
                result = {
                  'online': true,
                  'signal_dbm': null,
                  'status': 'unavailable',
                };
              case '/api/client/account':
                if (!authenticated) {
                  return http.Response('{"detail":"Sign in"}', 401);
                }
                result = {
                  'username': 'subscriber',
                  'first_name': 'Ava',
                  'last_name': 'Sample',
                  'phone': '07500000000',
                  'recharge_cost': '30000',
                  'currency': 'IQD',
                  'profile': '20 Mbps',
                  'expiration': '2026-12-01',
                  'profile_id': 3,
                  'transaction_id': 'a' * 32,
                  'can_recharge': true,
                  'fib_configured': true,
                  'payments': [],
                };
              case '/api/client/auto-login':
                authenticated = automatic;
                result = {'authenticated': automatic};
              case '/api/client/login-options':
                result = {'challenge_id': 'challenge', 'captcha_image': null};
              case '/api/client/login':
                expect(jsonDecode(request.body)['username'], 'subscriber');
                expect(jsonDecode(request.body)['password'], 'secret');
                authenticated = true;
                result = {'authenticated': true};
              case '/api/client/logout':
                authenticated = false;
                result = {'ok': true};
              case '/api/client/recharge':
                expect(jsonDecode(request.body), {
                  'transaction_id': 'a' * 32,
                  'expected_profile_id': 3,
                  'expected_expiration': '2026-12-01',
                  'pin': 'MY-CARD',
                });
                result = {'recharged': true};
              case '/api/client/cards':
                result = {
                  'items': [
                    for (var i = 0; i < 5; i++)
                      {
                        'profile_id': 97 + i,
                        'name': [
                          'AirLink Basic',
                          'AirLink Plus',
                          'AirLink Pro',
                          'AirLink Ultra',
                          'AirLink Max',
                        ][i],
                        'price_iqd': [
                          '20000',
                          '25000',
                          '32000',
                          '40000',
                          '50000',
                        ][i],
                        'price_source': 'retail',
                        'stock_status': 'no_cards',
                      },
                  ],
                  'synced_at': '2026-11-22T10:00:00Z',
                };
              case '/api/client/fib-quote':
                result = {
                  'items': [
                    {'id': '42', 'series': 'SERIES', 'price_iqd': '25000'},
                  ],
                };
              case '/api/client/payments':
                expect(jsonDecode(request.body), {
                  'transaction_id': 'a' * 32,
                  'expected_profile_id': 3,
                  'expected_expiration': '2026-12-01',
                  'expected_amount': '25000',
                  'radius_card_id': 42,
                  'radius_series': 'SERIES',
                });
                result = {
                  'id': 'b' * 32,
                  'status': 'pending',
                  'amount': '25000',
                  'currency': 'IQD',
                  'checkout': {'code': 'PAY-CODE'},
                };
              default:
                throw StateError('Unexpected request ${request.url}');
            }
            return http.Response(jsonEncode(result), 200);
          }),
        );
        await tester.pumpWidget(MaterialApp(home: ClientPortal(api: api)));
        await tester.pumpAndSettle();
        if (!automatic) {
          await tester.enterText(find.byType(TextField).at(0), 'subscriber');
          await tester.enterText(find.byType(TextField).at(1), 'secret');
          await tester.tap(find.text('Sign in'));
          await tester.pumpAndSettle();
        }
        expect(find.text('subscriber'), findsNWidgets(2));
        expect(find.text('20 Mbps'), findsOneWidget);
        expect(find.text('30000 IQD'), findsOneWidget);
        expect(find.text('Manager balance'), findsNothing);
        expect(find.text('FastPay'), findsNothing);
        expect(find.text('Start speed test'), findsOneWidget);
        expect(
          requests.where((r) => r.url.path == '/api/client/connection'),
          isEmpty,
        );
        expect(find.byType(NavigationDestination), findsNWidgets(5));
        expect(find.text('Our Cards'), findsOneWidget);
        expect(find.text('Recharge'), findsOneWidget);
        expect(find.text('SpeedTest'), findsOneWidget);
        final speedLink = tester
            .widgetList<Link>(find.byType(Link))
            .singleWhere((link) => link.uri?.host == 'www.speedtest.net');
        expect(speedLink.uri.toString(), 'https://www.speedtest.net/');
        expect(speedLink.target, LinkTarget.blank);
        await tester.tap(find.text('Our Cards'));
        await tester.pumpAndSettle();
        expect(
          find.text('AirLink plans synced from SAS4 Radius.'),
          findsOneWidget,
        );
        expect(find.text('AirLink Basic'), findsOneWidget);
        expect(find.text('20,000 IQD'), findsOneWidget);
        expect(find.text('50,000 IQD'), findsOneWidget);
        expect(find.byType(TextField), findsNothing);
        expect(
          requests.where((r) => r.url.path == '/api/client/payments'),
          isEmpty,
        );
        await tester.tap(find.byType(NavigationDestination).at(0));
        await tester.pumpAndSettle();
        await tester.ensureVisible(find.byType(TextField));
        await tester.pumpAndSettle();
        await tester.enterText(find.byType(TextField), 'MY-CARD');
        await tester.tap(find.byType(NavigationDestination).at(4));
        await tester.pumpAndSettle();
        expect(find.text('First name'), findsOneWidget);
        expect(find.text('Ava'), findsOneWidget);
        expect(find.text('Sample'), findsOneWidget);
        expect(find.text('07500000000'), findsOneWidget);
        expect(find.text('Recharge my account'), findsNothing);
        await tester.tap(find.byType(NavigationDestination).at(3));
        await tester.pumpAndSettle();
        expect(find.text('Telecommunication company'), findsOneWidget);
        expect(find.text('Start speed test'), findsNothing);
        await tester.tap(find.byType(NavigationDestination).at(1));
        await tester.pumpAndSettle();
        expect(find.text('Start speed test'), findsOneWidget);
        expect(find.text('Recharge my account'), findsNothing);
        await tester.tap(find.byType(NavigationDestination).at(0));
        await tester.pumpAndSettle();
        expect(find.text('Start speed test'), findsOneWidget);
        expect(find.text('subscriber'), findsNWidgets(2));
        expect(
          tester.widget<TextField>(find.byType(TextField)).controller!.text,
          'MY-CARD',
        );
        await tester.ensureVisible(find.text('Recharge my account'));
        await tester.pumpAndSettle();
        await tester.tap(find.text('Recharge my account'));
        await tester.pumpAndSettle();
        expect(
          find.text('Your account was recharged successfully.'),
          findsOneWidget,
        );
        await tester.ensureVisible(find.text('FIB Bank'));
        await tester.pumpAndSettle();
        await tester.tap(find.text('FIB Bank'));
        await tester.pumpAndSettle();
        expect(find.text('25000 IQD'), findsOneWidget);
        expect(
          find.text('30000 IQD'),
          findsOneWidget,
        ); // Account cost is separate from the FIB quote.
        expect(
          requests.where((r) => r.url.path == '/api/client/payments'),
          isEmpty,
        );
        await tester.ensureVisible(find.text('Continue to FIB payment'));
        await tester.pumpAndSettle();
        await tester.tap(find.text('Continue to FIB payment'));
        await tester.pumpAndSettle();
        expect(find.text('Payment code: PAY-CODE'), findsOneWidget);
        await tester.tap(find.byType(NavigationDestination).at(4));
        await tester.pumpAndSettle();
        await tester.ensureVisible(find.text('Sign out'));
        await tester.pumpAndSettle();
        await tester.tap(find.text('Sign out'));
        await tester.pumpAndSettle();
        expect(find.text('Sign in'), findsOneWidget);
        expect(find.byType(NavigationBar), findsNothing);
        expect(
          requests.where((r) => r.url.path == '/api/client/auto-login').length,
          1,
        );
        expect(tester.takeException(), isNull);
        await tester.pumpWidget(const SizedBox.shrink());
      },
    );
  }
}
