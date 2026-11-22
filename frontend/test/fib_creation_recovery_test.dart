import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:airlink_isp_os/api.dart';
import 'package:airlink_isp_os/sas4_recharge.dart';
import 'package:airlink_isp_os/payment_settings.dart';

void main() {
  testWidgets(
    'unknown creation requires checked confirmation and retry reviews fresh price',
    (tester) async {
      tester.view.physicalSize = const Size(1200, 1400);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final writes = <http.Request>[];
      final order = <String, dynamic>{
        'id': 'b' * 32,
        'provider': 'fib',
        'environment': 'production',
        'status': 'creation_unknown',
        'amount': '20000',
        'currency': 'IQD',
        'can_review_creation': true,
        'detail': 'Payment creation was not confirmed.',
      };
      final api = Api(
        client: MockClient((request) async {
          Object result;
          if (request.method == 'POST') {
            writes.add(request);
            if (request.url.path.endsWith('/test')) {
              result = {
                'authenticated': false,
                'environment': 'production',
                'detail': 'FIB rejected the merchant credentials.',
              };
            } else {
              expect(request.url.path.endsWith('/review-creation'), isTrue);
              expect(jsonDecode(request.body), {'confirmed_not_created': true});
              order.addAll({
                'status': 'creation_failed',
                'can_review_creation': false,
                'detail': 'The reserved card has been released.',
              });
              result = order;
            }
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
          } else if (request.url.path.endsWith('/radius-card')) {
            result = {
              'items': [
                {
                  'id': '42',
                  'series': 'SERIES-1',
                  'label': '20 Mbps',
                  'profile_id': 3,
                  'price_iqd': '20000',
                },
              ],
              'total': 1,
            };
          } else {
            result = {
              'username': 'customer',
              'profile_id': 3,
              'profile': '20 Mbps',
              'expiration': '2026-12-01',
              'transaction_id': 'c' * 32,
              'methods': {'card': true, 'credit': false},
            };
          }
          return http.Response(jsonEncode(result), 200);
        }),
      );
      api.user = {'role': 'owner'};
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(body: Sas4Recharge(api: api, userId: 7)),
        ),
      );
      await tester.pumpAndSettle();
      expect(writes, isEmpty);
      expect(find.text('Review price and retry'), findsNothing);
      expect(
        find.text(
          'You can close this window. Payment checks continue on the server.',
        ),
        findsNothing,
      );
      await tester.tap(find.text('Check FIB connection'));
      await tester.pumpAndSettle();
      expect(
        find.text('production: FIB rejected the merchant credentials.'),
        findsOneWidget,
      );
      expect(writes.single.url.path, '/api/payments/gateways/fib/test');
      await tester.tap(
        find.widgetWithText(OutlinedButton, 'Review unconfirmed payment'),
      );
      await tester.pumpAndSettle();
      final release = find.widgetWithText(
        FilledButton,
        'Release reserved card',
      );
      expect(tester.widget<FilledButton>(release).onPressed, isNull);
      await tester.tap(find.byType(CheckboxListTile));
      await tester.pumpAndSettle();
      await tester.tap(release);
      await tester.pumpAndSettle();
      expect(writes.length, 2);
      expect(find.text('Review price and retry'), findsOneWidget);
      await tester.tap(find.text('Review price and retry'));
      await tester.pumpAndSettle();
      expect(find.text('Customer payment: 20000 IQD'), findsOneWidget);
      expect(find.text('Continue to FIB payment'), findsOneWidget);
      expect(
        writes.length,
        2,
      ); // No automatic charge on review, testing, or retry preparation.
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets(
    'payment settings tests saved credentials without creating a charge',
    (tester) async {
      tester.view.physicalSize = const Size(1200, 1400);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final writes = <http.Request>[];
      final api = Api(
        client: MockClient((request) async {
          if (request.method == 'POST') {
            writes.add(request);
            return http.Response(
              '{"authenticated":false,"environment":"production","detail":"FIB rejected the merchant credentials."}',
              200,
            );
          }
          return http.Response(
            '[{"provider":"fib","merchant_id":"saved-client","environment":"production","configured":true}]',
            200,
          );
        }),
      );
      api.user = {'role': 'owner'};
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: SingleChildScrollView(
              child: PaymentSettings(api: api, embedded: true),
            ),
          ),
        ),
      );
      await tester.pumpAndSettle();
      await tester.tap(find.text('Test saved FIB connection'));
      await tester.pumpAndSettle();
      expect(writes.single.url.path, '/api/payments/gateways/fib/test');
      expect(
        find.text('production: FIB rejected the merchant credentials.'),
        findsOneWidget,
      );
      expect(tester.takeException(), isNull);
    },
  );
}
