import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:airlink_isp_os/api.dart';
import 'package:airlink_isp_os/sas4_recharge.dart';

void main() {
  for (final reopened in [false, true]) {
    testWidgets(
      'five-minute expiry hides payment controls and never reveals PIN (reopened: $reopened)',
      (tester) async {
        tester.view.physicalSize = const Size(1200, 1400);
        tester.view.devicePixelRatio = 1;
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);
        final created = DateTime.utc(2026, 11, 22, 12);
        var clock = reopened
            ? created.add(const Duration(minutes: 6))
            : created;
        var status = 'pending';
        final writes = <http.Request>[];
        Map<String, dynamic> payment() => {
          'id': 'b' * 32,
          'provider': 'fib',
          'environment': 'production',
          'status': status,
          'amount': '20000',
          'currency': 'IQD',
          'expires_at': created
              .add(const Duration(minutes: 5))
              .toIso8601String(),
          'checkout': {
            'code': 'PAYMENT-CODE',
            'qr_data': 'data:image/png;base64,%%%',
            'app_links': {
              'personal':
                  'https://p-stage.fib.iq/onlinePayment?identifier=test',
            },
          },
        };
        final api = Api(
          client: MockClient((request) async {
            if (request.method != 'GET') writes.add(request);
            Object result;
            if (request.url.path.endsWith('/methods')) {
              result = [
                {
                  'provider': 'fib',
                  'configured': true,
                  'environment': 'production',
                },
              ];
            } else if (request.url.path.endsWith('/payments/users/7')) {
              result = [payment()];
            } else if (request.url.path.contains('/orders/')) {
              result = payment();
            } else if (request.url.path.endsWith('/radius-card')) {
              result = {
                'items': [
                  {
                    'id': 'card-1',
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
                'profile': '20 Mbps',
                'profile_id': 3,
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
            home: Scaffold(
              body: Sas4Recharge(api: api, userId: 7, currentTime: () => clock),
            ),
          ),
        );
        await tester.pumpAndSettle();
        if (!reopened) {
          expect(find.text('Time left to pay: 05:00'), findsOneWidget);
          expect(find.text('Pay with FIB'), findsOneWidget);
          expect(find.text('Payment code: PAYMENT-CODE'), findsOneWidget);
          clock = created.add(const Duration(minutes: 4, seconds: 59));
          await tester.pump(const Duration(seconds: 1));
          expect(find.text('Time left to pay: 00:01'), findsOneWidget);
          clock = created.add(const Duration(minutes: 5));
          await tester.pump(const Duration(seconds: 1));
          await tester.pumpAndSettle();
        }
        expect(find.text('Pay with FIB'), findsNothing);
        expect(find.text('Copy customer payment link'), findsNothing);
        expect(find.text('Payment code: PAYMENT-CODE'), findsNothing);
        expect(find.text('Show recharge PIN'), findsNothing);
        expect(
          find.text(
            'Payment window expired. Waiting for FIB confirmation. The recharge PIN remains locked.',
          ),
          findsOneWidget,
        );
        expect(find.text('Start new payment'), findsNothing);
        status = 'expired';
        await tester.pump(const Duration(seconds: 5));
        await tester.pumpAndSettle();
        expect(
          find.text('Payment expired. No recharge PIN was issued or used.'),
          findsOneWidget,
        );
        expect(find.text('Start new payment'), findsOneWidget);
        expect(find.text('Show recharge PIN'), findsNothing);
        await tester.tap(find.text('Start new payment'));
        await tester.pumpAndSettle();
        expect(find.text('Continue to FIB payment'), findsOneWidget);
        expect(writes, isEmpty);
        expect(tester.takeException(), isNull);
        await tester.pumpWidget(const SizedBox());
      },
    );
  }
}
