import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:airlink_isp_os/api.dart';
import 'package:airlink_isp_os/sas4_recharge.dart';

void main() {
  testWidgets(
    'verified FIB payment reveals PIN and requires explicit card recharge',
    (tester) async {
      tester.view.physicalSize = const Size(1200, 1300);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final writes = <http.Request>[];
      final order = {
        'id': 'b' * 32,
        'provider': 'fib',
        'environment': 'production',
        'status': 'pending',
        'amount': '2500',
        'currency': 'IQD',
        'fulfillment': 'saved_pin',
        'card_label': '20 Mbps',
        'checkout': {'code': 'BANK-PAYMENT-CODE'},
      };
      final api = Api(
        client: MockClient((request) async {
          Object result;
          if (request.method == 'POST') {
            writes.add(request);
            result = request.url.path.endsWith('/pin')
                ? {'pin': 'ISSUED-SAS4-PIN'}
                : {'recharged': true};
          } else if (request.url.path.endsWith('/methods')) {
            result = [
              {
                'provider': 'fib',
                'configured': true,
                'environment': 'production',
              },
            ];
          } else if (request.url.path.endsWith('/payments/users/7')) {
            result = [order];
          } else if (request.url.path.contains('/orders/')) {
            result = {...order, 'status': 'pin_ready'};
          } else if (request.url.path.endsWith('/radius-card')) {
            result = {'items': [], 'total': 0};
          } else {
            result = {
              'username': 'customer',
              'profile_id': 3,
              'profile': '20 Mbps',
              'expiration': '2026-12-01',
              'customer_price': '2500',
              'currency': 'IQD',
              'methods': {'credit': false, 'card': true, 'extend': false},
              'transaction_id': 'a' * 32,
            };
          }
          return http.Response(jsonEncode(result), 200);
        }),
      );
      api.user = {'role': 'owner'};
      await tester.pumpWidget(
        MaterialApp(
          home: Builder(
            builder: (context) => Scaffold(
              body: FilledButton(
                onPressed: () => showDialog(
                  context: context,
                  builder: (_) => Sas4Recharge(api: api, userId: 7),
                ),
                child: const Text('Open'),
              ),
            ),
          ),
        ),
      );
      await tester.tap(find.text('Open'));
      await tester.pumpAndSettle();
      expect(find.text('Show recharge PIN'), findsNothing);
      expect(writes, isEmpty);
      await tester.pump(const Duration(seconds: 5));
      await tester.pumpAndSettle();
      expect(find.text('Show recharge PIN'), findsOneWidget);
      expect(find.text('ISSUED-SAS4-PIN'), findsNothing);
      expect(writes, isEmpty);
      await tester.tap(find.text('Show recharge PIN'));
      await tester.pumpAndSettle();
      expect(find.byKey(const ValueKey('issued-recharge-pin')), findsOneWidget);
      expect(writes.single.url.path, '/api/payments/orders/${'b' * 32}/pin');
      await tester.tap(find.text('Use PIN to recharge'));
      await tester.pumpAndSettle();
      expect(writes.length, 1);
      expect(
        tester
            .widget<TextFormField>(
              find.byKey(const ValueKey('recharge-card-pin')),
            )
            .controller!
            .text,
        'ISSUED-SAS4-PIN',
      );
      await tester.tap(find.widgetWithText(FilledButton, 'Recharge card'));
      await tester.pumpAndSettle();
      expect(writes.length, 2);
      expect(writes.last.url.path, '/api/integrations/sas4/users/7/recharge');
      expect(jsonDecode(writes.last.body), {
        'method': 'card',
        'pin': 'ISSUED-SAS4-PIN',
        'transaction_id': 'b' * 32,
      });
      await tester.pumpWidget(const SizedBox.shrink());
    },
  );
}
