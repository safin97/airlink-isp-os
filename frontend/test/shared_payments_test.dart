import 'dart:convert';
import 'package:airlink_isp_os/api.dart';
import 'package:airlink_isp_os/sas4_recharge.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

void main() {
  for (final provider in ['fib', 'fastpay']) {
    for (final configured in [true, false]) {
      testWidgets('manager uses owner $provider configuration: $configured', (
        tester,
      ) async {
        tester.view.physicalSize = const Size(1200, 1100);
        tester.view.devicePixelRatio = 1;
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);
        final writes = <http.Request>[];
        final api =
            Api(
                client: MockClient((request) async {
                  expect(request.url.path.contains('/gateways'), isFalse);
                  Object data;
                  if (request.method == 'POST') {
                    writes.add(request);
                    data = {
                      'id': 'b' * 32,
                      'provider': provider,
                      'status': 'sandbox_paid',
                      'environment': 'sandbox',
                      'amount': '2500',
                      'currency': 'IQD',
                    };
                  } else if (request.url.path.endsWith('/methods')) {
                    data = [
                      for (final p in ['fib', 'fastpay'])
                        {
                          'provider': p,
                          'configured': configured,
                          'environment': 'sandbox',
                        },
                    ];
                  } else if (request.url.path.endsWith('/radius-card')) {
                    data = {
                      'items': [
                        {
                          'id': '42',
                          'series': 'SERIES-1',
                          'profile_id': 3,
                          'label': 'Matching plan',
                          'price_iqd': '2500',
                        },
                      ],
                    };
                  } else if (request.url.path.endsWith('/payments/users/7')) {
                    data = [];
                  } else {
                    data = {
                      'username': 'customer',
                      'profile_id': 3,
                      'expiration': '2026-12-01',
                      'manager_cost': '2000',
                      'customer_price': '2500',
                      'currency': 'IQD',
                      'methods': {'credit': true, 'card': true},
                      'transaction_id': 'a' * 32,
                    };
                  }
                  return http.Response(jsonEncode(data), 200);
                }),
              )
              ..user = {
                'role': 'manager',
                'sections': ['isp_card', 'fib_recharge'],
                'editable_sections': ['isp_card', 'fib_recharge'],
              };
        await tester.pumpWidget(
          MaterialApp(
            home: Scaffold(body: Sas4Recharge(api: api, userId: 7)),
          ),
        );
        await tester.pumpAndSettle();
        await tester.tap(find.byKey(ValueKey('recharge-method-$provider')));
        await tester.pumpAndSettle();
        expect(find.text('Payment setup'), findsNothing);
        final button = find.widgetWithText(
          FilledButton,
          provider == 'fib' ? 'Continue to FIB payment' : 'Create payment',
        );
        expect(
          tester.widget<FilledButton>(button).onPressed,
          configured ? isNotNull : isNull,
        );
        if (configured) {
          await tester.tap(button);
          await tester.pumpAndSettle();
          expect(writes.length, 1);
          final body = jsonDecode(writes.single.body);
          expect(body['provider'], provider);
          expect(body['expected_amount'], '2500');
          expect(body.containsKey('merchant_id'), isFalse);
          expect(body.containsKey('secret'), isFalse);
        } else {
          expect(
            find.textContaining('Ask the owner to complete Payment setup'),
            findsOneWidget,
          );
          expect(writes, isEmpty);
        }
        await tester.pumpWidget(const SizedBox());
      });
    }
  }
}
