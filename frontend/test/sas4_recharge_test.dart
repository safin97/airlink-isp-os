import 'dart:async';
import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:airlink_isp_os/api.dart';
import 'package:airlink_isp_os/sas4_user_details.dart';

void main() {
  for (final rechargeSucceeds in [true, false]) {
    testWidgets(
      'recharge preserves unsaved edits; success: $rechargeSucceeds',
      (tester) async {
        tester.view.physicalSize = const Size(1200, 1000);
        tester.view.devicePixelRatio = 1;
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);
        final writes = <http.Request>[];
        final profileWrites = <http.Request>[];
        final pending = Completer<http.Response>();
        bool recharged = false;
        final api = Api(
          client: MockClient((request) async {
            if (request.method == 'PUT') {
              profileWrites.add(request);
              return http.Response('{"saved":true}', 200);
            }
            if (request.method == 'POST') {
              writes.add(request);
              return pending.future;
            }
            if (request.url.path.endsWith('/recharge')) {
              expect(profileWrites, isEmpty);
              return http.Response(
                jsonEncode({
                  'username': 'customer',
                  'profile': '20 Mbps',
                  'expiration': '2026-11-01',
                  'transaction_id': 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
                }),
                200,
              );
            }
            return http.Response(
              jsonEncode({
                'username': 'customer',
                'can_recharge': true,
                'fields': [
                  {
                    'key': 'firstname',
                    'kind': 'text',
                    'label': 'First name',
                    'editable': true,
                    'value': profileWrites.isEmpty
                        ? 'Original'
                        : 'Unsaved edit',
                  },
                  {
                    'key': 'expiration',
                    'kind': 'datetime',
                    'label': 'Card expiry date',
                    'editable': false,
                    'value': recharged
                        ? '2026-12-01 00:00:00'
                        : '2026-11-01 00:00:00',
                  },
                ],
              }),
              200,
            );
          }),
        );
        api.user = {'role': 'owner'};
        await tester.pumpWidget(
          MaterialApp(home: Sas4UserDetails(api: api, userId: 7)),
        );
        await tester.pumpAndSettle();
        expect(find.text('Recharge card'), findsOneWidget);
        final firstName = find.byWidgetPredicate(
          (w) => w is TextField && w.decoration?.labelText == 'First name',
        );
        await tester.tap(find.text('Edit'));
        await tester.pumpAndSettle();
        await tester.enterText(firstName, 'Unsaved edit');
        await tester.pump();
        expect(profileWrites, isEmpty);
        await tester.tap(find.text('Recharge card'));
        await tester.pumpAndSettle();
        expect(profileWrites, isEmpty);
        expect(
          find.textContaining('Your edits will stay unsaved.'),
          findsOneWidget,
        );
        expect(find.text('User: customer'), findsOneWidget);
        expect(writes, isEmpty);
        final input = find.byWidgetPredicate(
          (w) => w is TextField && w.decoration?.labelText == 'Card PIN',
        );
        await tester.enterText(input, 'TEST-CARD-PIN');
        final button = find.widgetWithText(FilledButton, 'Recharge card');
        await tester.tap(button);
        await tester.pump();
        expect(writes.length, 1);
        expect(
          tester
              .widget<FilledButton>(
                find.widgetWithText(FilledButton, 'Submitting…'),
              )
              .onPressed,
          isNull,
        );
        expect(jsonDecode(writes.single.body), {
          'method': 'card',
          'pin': 'TEST-CARD-PIN',
          'transaction_id': 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',
        });
        expect(
          writes.single.url.path,
          '/api/integrations/sas4/users/7/recharge',
        );
        recharged = rechargeSucceeds;
        pending.complete(
          rechargeSucceeds
              ? http.Response('{"recharged":true}', 200)
              : http.Response('{"detail":"Recharge rejected"}', 400),
        );
        await tester.pumpAndSettle();
        if (rechargeSucceeds) {
          expect(find.text('Card recharged successfully.'), findsOneWidget);
        } else {
          expect(find.textContaining('Recharge rejected'), findsOneWidget);
          await tester.tap(find.text('Close'));
          await tester.pumpAndSettle();
        }
        final expiry = tester.widget<TextField>(
          find.byWidgetPredicate(
            (w) =>
                w is TextField && w.decoration?.labelText == 'Card expiry date',
          ),
        );
        expect(
          expiry.controller!.text,
          rechargeSucceeds ? '2026-12-01 00:00:00' : '2026-11-01 00:00:00',
        );
        expect(find.text('TEST-CARD-PIN'), findsNothing);
        expect(writes.length, 1);
        expect(profileWrites, isEmpty);
        expect(
          tester.widget<TextField>(firstName).controller!.text,
          'Unsaved edit',
        );
        expect(
          tester
              .widget<FilledButton>(
                find.widgetWithText(FilledButton, 'Save changes'),
              )
              .onPressed,
          isNotNull,
        );
        await tester.tap(find.text('Save changes'));
        await tester.pumpAndSettle();
        expect(jsonDecode(profileWrites.single.body), {
          'changes': {'firstname': 'Unsaved edit'},
        });
        expect(tester.takeException(), isNull);
        await tester.pumpWidget(const SizedBox());
      },
    );
  }
}
