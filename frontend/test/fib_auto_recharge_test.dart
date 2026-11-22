import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:url_launcher/link.dart';
import 'package:airlink_isp_os/api.dart';
import 'package:airlink_isp_os/sas4_recharge.dart';

void main() {
  for (final platform in [TargetPlatform.android, TargetPlatform.iOS]) {
    testWidgets(
      'FIB QR and mobile app link wait for server automatic recharge on $platform',
      (tester) async {
        tester.view.physicalSize = const Size(390, 844);
        tester.view.devicePixelRatio = 1;
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);
        const appLink = 'https://p.fib.iq/onlinePayment?identifier=TEST-CODE';
        var status = 'pending';
        final writes = <http.Request>[];
        bool? returned;
        Map<String, dynamic> payment() => {
          'id': 'b' * 32,
          'provider': 'fib',
          'environment': 'production',
          'status': status,
          'auto_recharge': true,
          'fulfillment': 'saved_pin',
          'amount': '20000',
          'currency': 'IQD',
          'checkout': {
            'code': 'PAYMENT-CODE',
            'app_links': {'personal': appLink},
            'qr_data':
                'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=',
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
              result = {'items': [], 'total': 0};
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
            theme: ThemeData(platform: platform),
            home: Builder(
              builder: (context) => Scaffold(
                body: FilledButton(
                  onPressed: () async {
                    returned = await showDialog<bool>(
                      context: context,
                      builder: (_) => Sas4Recharge(api: api, userId: 7),
                    );
                  },
                  child: const Text('Open'),
                ),
              ),
            ),
          ),
        );
        await tester.tap(find.text('Open'));
        await tester.pumpAndSettle();
        expect(
          find.text(
            'After FIB verifies payment, your reserved card will automatically recharge this customer.',
          ),
          findsOneWidget,
        );
        expect(find.byKey(const ValueKey('bank-payment-qr')), findsOneWidget);
        final link = tester.widget<Link>(find.byType(Link));
        expect(link.uri.toString(), appLink);
        expect(link.target, LinkTarget.self);
        expect(
          tester
              .widget<FilledButton>(
                find.byKey(const ValueKey('fib-pay-personal')),
              )
              .onPressed,
          isNotNull,
        );
        expect(find.text('Show recharge PIN'), findsNothing);
        expect(tester.takeException(), isNull);
        status = 'activating';
        await tester.pump(const Duration(seconds: 5));
        await tester.pumpAndSettle();
        expect(
          find.text('Payment verified. Recharging service…'),
          findsOneWidget,
        );
        expect(find.text('Pay with FIB'), findsNothing);
        expect(find.text('Use PIN to recharge'), findsNothing);
        expect(returned, isNull);
        status = 'completed';
        await tester.pump(const Duration(seconds: 5));
        await tester.pumpAndSettle();
        expect(returned, isTrue);
        expect(find.byType(Sas4Recharge), findsNothing);
        expect(writes, isEmpty);
        expect(tester.takeException(), isNull);
      },
    );
  }
}
