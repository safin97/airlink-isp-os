import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:airlink_isp_os/api.dart';
import 'package:airlink_isp_os/card_system.dart';
import 'package:airlink_isp_os/sas4_recharge.dart';

void main() {
  testWidgets('owner assigns existing PIN a profile and separate FIB price', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(1200, 1400);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final writes = <http.Request>[];
    final card = <String, dynamic>{
      'id': 'card-1',
      'label': 'Existing card',
      'state': 'available',
      'profile_id': null,
      'price_iqd': null,
    };
    final api = Api(
      client: MockClient((request) async {
        if (request.method == 'PUT') {
          writes.add(request);
          card.addAll(jsonDecode(request.body) as Map<String, dynamic>);
          return http.Response(jsonEncode(card), 200);
        }
        if (request.url.path.endsWith('/profiles')) {
          return http.Response(
            '[{"id":3,"name":"20 Mbps"},{"id":4,"name":"40 Mbps"}]',
            200,
          );
        }
        return http.Response(
          jsonEncode({
            'items': [card],
            'total': 1,
          }),
          200,
        );
      }),
    );
    api.user = {'role': 'owner'};
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: SingleChildScrollView(child: SavedCardInventory(api: api)),
        ),
      ),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.byTooltip('Card profile and price'));
    await tester.pumpAndSettle();
    final dialog = find.byType(AlertDialog);
    await tester.tap(
      find.descendant(
        of: dialog,
        matching: find.byType(DropdownButtonFormField<int>),
      ),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.text('20 Mbps').last);
    await tester.pumpAndSettle();
    await tester.enterText(
      find.descendant(of: dialog, matching: find.byType(TextFormField)),
      '17500.50',
    );
    await tester.tap(find.widgetWithText(FilledButton, 'Save'));
    await tester.pumpAndSettle();
    expect(writes.single.url.path, '/api/card-system/card-1/profile');
    expect(jsonDecode(writes.single.body), {
      'profile_id': 3,
      'price_iqd': '17500.50',
    });
    expect(find.textContaining('20 Mbps · 17500.50 IQD'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  for (final cards in [
    <Map<String, dynamic>>[],
    [
      {
        'id': 'wrong-profile',
        'label': '40 Mbps',
        'profile_id': 4,
        'price_iqd': '1000',
      },
    ],
  ]) {
    testWidgets(
      'FIB cannot pay without matching inventory (${cards.length} returned)',
      (tester) async {
        tester.view.physicalSize = const Size(1200, 1300);
        tester.view.devicePixelRatio = 1;
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);
        final api = Api(
          client: MockClient((request) async {
            expect(request.method, 'GET');
            Object data;
            if (request.url.path.endsWith('/methods')) {
              data = [
                {
                  'provider': 'fib',
                  'configured': true,
                  'environment': 'production',
                },
              ];
            } else if (request.url.path.endsWith('/payments/users/7')) {
              data = [];
            } else if (request.url.path.endsWith('/radius-card')) {
              expect(request.url.queryParameters['profile_id'], '3');
              data = {'items': cards, 'total': cards.length};
            } else {
              data = {
                'username': 'customer',
                'profile': '20 Mbps',
                'profile_id': 3,
                'customer_price': '9999',
                'currency': 'IQD',
                'methods': {'card': true, 'credit': false},
                'transaction_id': 'a' * 32,
              };
            }
            return http.Response(jsonEncode(data), 200);
          }),
        );
        api.user = {'role': 'owner'};
        await tester.pumpWidget(
          MaterialApp(
            home: Scaffold(body: Sas4Recharge(api: api, userId: 7)),
          ),
        );
        await tester.pumpAndSettle();
        await tester.tap(find.byKey(const ValueKey('recharge-method-fib')));
        await tester.pumpAndSettle();
        expect(find.text('Customer payment: Unavailable IQD'), findsOneWidget);
        expect(
          find.text(
            'No unused SAS4 Radius card matches this profile. Add unused cards in SAS4 Radius, then refresh.',
          ),
          findsOneWidget,
        );
        expect(
          tester
              .widget<FilledButton>(
                find.widgetWithText(FilledButton, 'Continue to FIB payment'),
              )
              .onPressed,
          isNull,
        );
        expect(find.text('Pay with FIB'), findsNothing);
        expect(tester.takeException(), isNull);
      },
    );
  }
}
