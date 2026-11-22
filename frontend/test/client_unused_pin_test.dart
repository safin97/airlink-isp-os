import 'dart:async';
import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:airlink_isp_os/api.dart';
import 'package:airlink_isp_os/client_portal.dart';

void main() {
  testWidgets(
    'FIB click checks fresh unused stock and blocks checkout on empty or failed checks',
    (tester) async {
      tester.view.physicalSize = const Size(480, 1400);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      var quote = Completer<http.Response>();
      var checks = 0;
      final api = Api(
        client: MockClient((request) async {
          expect(
            request.method,
            'GET',
          ); // Browsing/checking must not create a bank payment.
          if (request.url.path == '/api/client/fib-quote') {
            checks++;
            return quote.future;
          }
          expect(request.url.path, '/api/client/account');
          return http.Response(
            jsonEncode({
              'username': 'subscriber',
              'profile': 'AirLink Plus',
              'profile_id': 98,
              'expiration': '2026-12-01',
              'recharge_cost': '25000',
              'currency': 'IQD',
              'transaction_id': 'a' * 32,
              'can_recharge': true,
              'fib_configured': true,
              'payments': [],
            }),
            200,
          );
        }),
      );
      await tester.pumpWidget(MaterialApp(home: ClientPortal(api: api)));
      await tester.pumpAndSettle();
      expect(checks, 0);
      await tester.ensureVisible(find.text('FIB Bank'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('FIB Bank'));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 50));
      expect(checks, 1);
      expect(find.text('Checking SAS4 for an unused PIN…'), findsOneWidget);
      expect(
        tester
            .widget<FilledButton>(
              find.widgetWithText(FilledButton, 'Checking unused PIN…'),
            )
            .onPressed,
        isNull,
      );
      quote.complete(http.Response('{"items":[]}', 200));
      await tester.pumpAndSettle();
      expect(find.textContaining('No unused PIN is available'), findsOneWidget);
      expect(
        tester
            .widget<FilledButton>(
              find.widgetWithText(FilledButton, 'Continue to FIB payment'),
            )
            .onPressed,
        isNull,
      );
      quote = Completer<http.Response>();
      await tester.ensureVisible(find.text('FIB Bank'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('FIB Bank'));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 50));
      expect(checks, 2);
      quote.complete(
        http.Response(
          jsonEncode({
            'items': [
              {'id': '42', 'series': 'SERIES', 'price_iqd': '25000'},
            ],
          }),
          200,
        ),
      );
      await tester.pumpAndSettle();
      expect(find.text('Unused PIN available'), findsOneWidget);
      expect(
        tester
            .widget<FilledButton>(
              find.widgetWithText(FilledButton, 'Continue to FIB payment'),
            )
            .onPressed,
        isNotNull,
      );
      quote = Completer<http.Response>();
      await tester.ensureVisible(find.text('FIB Bank'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('FIB Bank'));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 50));
      expect(find.text('Unused PIN available'), findsNothing);
      quote.complete(http.Response('{"detail":"SAS4 unavailable"}', 502));
      await tester.pumpAndSettle();
      expect(checks, 3);
      expect(find.text('SAS4 unavailable'), findsOneWidget);
      expect(
        tester
            .widget<FilledButton>(
              find.widgetWithText(FilledButton, 'Continue to FIB payment'),
            )
            .onPressed,
        isNull,
      );
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox.shrink());
    },
  );
}
