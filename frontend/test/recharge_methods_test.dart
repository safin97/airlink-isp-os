import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:airlink_isp_os/api.dart';
import 'package:airlink_isp_os/sas4_recharge.dart';

void main() {
  for (final method in ['credit', 'extend', 'fib']) {
    testWidgets(
      'recharge method $method uses the reviewed amount and Test default',
      (tester) async {
        tester.view.physicalSize = const Size(1200, 1100);
        tester.view.devicePixelRatio = 1;
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);
        final writes = <http.Request>[];
        final api = Api(
          client: MockClient((request) async {
            if (request.method == 'POST') {
              writes.add(request);
              return http.Response(
                jsonEncode(
                  method == 'fib'
                      ? {
                          'id': 'order-1',
                          'status': 'pending',
                          'provider': 'fib',
                          'environment': 'sandbox',
                          'amount': '2500',
                          'currency': 'IQD',
                          'checkout': {'code': 'test-code'},
                        }
                      : {'recharged': true},
                ),
                200,
              );
            }
            if (request.url.path.endsWith('/gateways')) {
              return http.Response(
                '[{"provider":"fib","configured":true,"environment":"sandbox"}]',
                200,
              );
            }
            if (request.url.path.endsWith('/payments/users/7')) {
              return http.Response('[]', 200);
            }
            if (request.url.path.contains('/orders/')) {
              return http.Response(
                '{"id":"order-1","status":"sandbox_paid","provider":"fib","environment":"sandbox","amount":"2500","currency":"IQD"}',
                200,
              );
            }
            return http.Response(
              jsonEncode({
                'username': 'customer',
                'profile_id': 3,
                'profile': '20 Mbps',
                'expiration': '2026-12-01 00:00:00',
                'manager_cost': '2000',
                'customer_price': '2500',
                'currency': 'IQD',
                'manager_balance': '50000',
                'methods': {'credit': true, 'extend': true, 'card': true},
                'transaction_id': 'a' * 32,
                'extensions': [
                  {'id': 12, 'name': 'Other'},
                  {'id': 11, 'name': 'Test'},
                ],
                'extension': {'id': 11, 'name': 'Test', 'cost': '0'},
              }),
              200,
            );
          }),
        );
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
        expect(writes, isEmpty);
        if (method != 'credit') {
          await tester.tap(find.byType(DropdownButtonFormField<String>));
          await tester.pumpAndSettle();
          await tester.tap(
            find.text(method == 'extend' ? 'Extend service' : 'FIB Bank').last,
          );
          await tester.pumpAndSettle();
        }
        if (method == 'extend') {
          expect(
            tester
                .widget<DropdownButtonFormField<int>>(
                  find.byType(DropdownButtonFormField<int>),
                )
                .initialValue,
            11,
          );
          expect(find.text('Test'), findsWidgets);
        }
        expect(writes, isEmpty);
        await tester.tap(
          find.widgetWithText(
            FilledButton,
            method == 'extend'
                ? 'Extend service'
                : method == 'fib'
                ? 'Create payment'
                : 'Recharge card',
          ),
        );
        await tester.pumpAndSettle();
        final body = jsonDecode(writes.single.body);
        if (method == 'fib') {
          expect(body['provider'], 'fib');
          expect(body['expected_amount'], '2500');
          expect(find.text('Payment code: test-code'), findsOneWidget);
          await tester.pump(const Duration(seconds: 5));
          await tester.pumpAndSettle();
          expect(
            find.text('Test payment verified. No real service was recharged.'),
            findsOneWidget,
          );
        } else {
          expect(body['method'], method);
          expect(body['expected_cost'], method == 'extend' ? '0' : '2000');
          expect(body['expected_profile_id'], 3);
          if (method == 'extend') expect(body['extension_id'], 11);
        }
        expect(writes.length, 1);
        expect(tester.takeException(), isNull);
        await tester.pumpWidget(const SizedBox());
      },
    );
  }
}
