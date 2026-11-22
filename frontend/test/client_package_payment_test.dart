import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:airlink_isp_os/api.dart';
import 'package:airlink_isp_os/client_portal.dart';
import 'package:airlink_isp_os/client_plan_card.dart';

void main() {
  testWidgets(
    'package Pay selects a different plan and waits for verified payment',
    (tester) async {
      tester.view.physicalSize = const Size(390, 844);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      var profile = 97, quotes = 0, payments = 0;
      const names = [
        'AirLink Basic',
        'AirLink Plus',
        'AirLink Pro',
        'AirLink Ultra',
        'AirLink Max',
      ];
      final api = Api(
        client: MockClient((request) async {
          Object data;
          switch (request.url.path) {
            case '/api/client/account':
              data = {
                'username': 'subscriber',
                'profile_id': profile,
                'profile': names[profile - 97],
                'expiration': '2026-12-01',
                'recharge_cost': '25000',
                'currency': 'IQD',
                'transaction_id': 'a' * 32,
                'can_recharge': true,
                'fib_configured': true,
                'payments': [],
              };
            case '/api/client/cards':
              data = {
                'items': [
                  for (var i = 0; i < 5; i++)
                    {
                      'profile_id': 97 + i,
                      'name': names[i],
                      'price_iqd': '25000',
                      'stock_status': 'no_cards',
                    },
                ],
              };
            case '/api/client/fib-quote':
              quotes++;
              expect(request.url.queryParameters, {'package_profile_id': '98'});
              data = {
                'items': [
                  {
                    'id': '42',
                    'series': 'PLUS',
                    'profile_id': 98,
                    'price_iqd': '25000',
                  },
                ],
              };
            case '/api/client/payments':
              payments++;
              expect(request.method, 'POST');
              expect(jsonDecode(request.body), {
                'transaction_id': 'a' * 32,
                'expected_profile_id': 97,
                'expected_expiration': '2026-12-01',
                'package_profile_id': 98,
                'expected_amount': '25000',
                'radius_card_id': 42,
                'radius_series': 'PLUS',
              });
              expect(profile, 97);
              data = {
                'id': 'b' * 32,
                'status': 'pending',
                'amount': '25000',
                'currency': 'IQD',
                'profile': 'AirLink Plus',
                'checkout': {'code': 'PAY-CODE'},
              };
            default:
              expect(request.url.path, '/api/client/payments/${'b' * 32}');
              profile = 98;
              data = {
                'id': 'b' * 32,
                'status': 'completed',
                'amount': '25000',
                'currency': 'IQD',
                'profile': 'AirLink Plus',
              };
          }
          return http.Response(jsonEncode(data), 200);
        }),
      );
      await tester.pumpWidget(MaterialApp(home: ClientPortal(api: api)));
      await tester.pumpAndSettle();
      await tester.tap(find.byType(NavigationDestination).at(2));
      await tester.pumpAndSettle();
      expect(find.text('Pay'), findsNWidgets(5));
      final plusPay = find.descendant(
        of: find.byType(ClientPlanCard).at(1),
        matching: find.text('Pay'),
      );
      await tester.ensureVisible(plusPay);
      await tester.pumpAndSettle();
      await tester.tap(plusPay);
      await tester.pumpAndSettle();
      expect(quotes, 1);
      expect(payments, 0);
      expect(profile, 97);
      expect(find.text('Selected package'), findsOneWidget);
      expect(find.text('AirLink Plus'), findsOneWidget);
      expect(find.text('AirLink Basic'), findsOneWidget);
      expect(
        tester
            .widget<ChoiceChip>(find.widgetWithText(ChoiceChip, 'FIB Bank'))
            .selected,
        true,
      );
      await tester.ensureVisible(find.text('Continue to FIB payment'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Continue to FIB payment'));
      await tester.pumpAndSettle();
      expect(payments, 1);
      expect(profile, 97);
      expect(find.text('Payment code: PAY-CODE'), findsOneWidget);
      await tester.tap(find.byType(NavigationDestination).at(2));
      await tester.pumpAndSettle();
      final basicPay = find.descendant(
        of: find.byType(ClientPlanCard).first,
        matching: find.text('Pay'),
      );
      await tester.ensureVisible(basicPay);
      await tester.pumpAndSettle();
      await tester.tap(basicPay);
      await tester.pumpAndSettle();
      expect(quotes, 1);
      expect(payments, 1);
      expect(
        find.textContaining('Finish or resolve your existing payment'),
        findsOneWidget,
      );
      await tester.ensureVisible(find.text('Refresh payment status'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Refresh payment status'));
      await tester.pumpAndSettle();
      expect(
        find.text(
          'Payment verified. Your internet account has been recharged.',
        ),
        findsOneWidget,
      );
      expect(profile, 98);
      expect(find.text('AirLink Basic'), findsNothing);
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox.shrink());
    },
  );
}
