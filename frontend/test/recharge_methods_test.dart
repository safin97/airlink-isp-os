import 'dart:convert';
import 'package:url_launcher/link.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:airlink_isp_os/api.dart';
import 'package:airlink_isp_os/sas4_recharge.dart';

void main() {
  const qrPng =
      'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=';
  for (final scenario in [('credit', false), ('fib', false), ('fib', true)]) {
    final (method, invalidQr) = scenario;
    testWidgets('recharge method $method uses reviewed amount (invalid QR: $invalidQr)', (
      tester,
    ) async {
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
                        'provider': method,
                        'environment': 'sandbox',
                        'amount': '2500',
                        'currency': 'IQD',
                        'checkout': {
                          'code': 'test-code',
                          'app_links': {
                            'personal':
                                'https://personal.stage.first-iraqi-bank.co/?link=payment-code',
                          },
                          'qr_data':
                              'data:image/png;base64,${invalidQr ? '%%%' : qrPng}',
                        },
                      }
                    : {'recharged': true},
              ),
              200,
            );
          }
          if (request.url.path.endsWith('/methods')) {
            return http.Response(
              '[{"provider":"fib","configured":true,"environment":"sandbox"},{"provider":"fastpay","configured":true,"environment":"sandbox"}]',
              200,
            );
          }
          if (request.url.path.endsWith('/radius-card')) {
            return http.Response(
              '{"items":[{"id":"42","series":"SERIES-1","label":"20 Mbps","profile_id":3,"price_iqd":"2500"}],"total":1}',
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
              'customer_price': method == 'fib' ? '9999' : '2500',
              'currency': method == 'fib' ? null : 'IQD',
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
      expect(writes, isEmpty);
      for (final type in ['credit', 'fib', 'fastpay']) {
        expect(find.byKey(ValueKey('recharge-method-$type')), findsOneWidget);
      }
      for (final type in ['bank', 'extend', 'card']) {
        expect(find.byKey(ValueKey('recharge-method-$type')), findsNothing);
      }
      expect(find.text('Bank Card'), findsNothing);
      expect(find.text('FastPay'), findsOneWidget);
      if (method != 'credit') {
        await tester.tap(find.byKey(ValueKey('recharge-method-$method')));
        await tester.pumpAndSettle();
      }
      expect(writes, isEmpty);
      if (method == 'fib') {
        expect(find.text('Customer payment: 2500 IQD'), findsOneWidget);
        expect(find.byKey(const ValueKey('fib-selected-card')), findsOneWidget);
        expect(find.byType(DropdownButtonFormField<String>), findsNothing);
        expect(find.byKey(const ValueKey('fib-payment-amount')), findsNothing);
        expect(
          tester
              .widget<FilledButton>(
                find.widgetWithText(FilledButton, 'Continue to FIB payment'),
              )
              .onPressed,
          isNotNull,
        );
      }
      await tester.tap(
        find.widgetWithText(
          FilledButton,
          method == 'fib' ? 'Continue to FIB payment' : 'Recharge card',
        ),
      );
      await tester.pumpAndSettle();
      final body = jsonDecode(writes.single.body);
      if (method == 'fib') {
        expect(body['provider'], 'fib');
        expect(body['card_source'], 'radius_pin');
        expect(body['radius_card_id'], 42);
        expect(body['radius_series'], 'SERIES-1');
        expect(body.containsKey('card_id'), isFalse);
        expect(body['expected_amount'], '2500');
        expect(body.containsKey('amount_iqd'), isFalse);
        expect(body.containsKey('expected_cost'), isFalse);
        expect(writes.single.url.path, '/api/payments/users/7');
        expect(find.text('2500 IQD'), findsOneWidget);
        expect(
          find.text('Scan this QR code with FIB Bank to pay'),
          findsOneWidget,
        );
        if (invalidQr) {
          expect(
            find.text('QR image unavailable. Use the payment code below.'),
            findsOneWidget,
          );
        } else {
          expect(find.byKey(const ValueKey('bank-payment-qr')), findsOneWidget);
          final qr = tester.widget<Image>(find.byType(Image));
          expect((qr.image as MemoryImage).bytes, base64Decode(qrPng));
        }
        expect(find.text('Payment code: test-code'), findsOneWidget);
        expect(find.text('Pay with FIB'), findsOneWidget);
        final link = tester.widget<Link>(find.byType(Link));
        expect(
          link.uri.toString(),
          'https://personal.stage.first-iraqi-bank.co/?link=payment-code',
        );
        expect(find.text('Copy customer payment link'), findsOneWidget);
        await tester.pump(const Duration(seconds: 5));
        await tester.pumpAndSettle();
        expect(
          find.text('Test payment verified. No real service was recharged.'),
          findsOneWidget,
        );
        expect(find.byKey(const ValueKey('bank-payment-qr')), findsNothing);
      } else {
        expect(body['method'], method);
        expect(body['expected_cost'], '2000');
        expect(body['expected_profile_id'], 3);
      }
      expect(writes.length, 1);
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox());
    });
  }
}
