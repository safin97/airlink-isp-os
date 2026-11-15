import 'dart:convert';
import 'package:airlink_isp_os/api.dart';
import 'package:airlink_isp_os/recharge_telegram.dart';
import 'package:airlink_isp_os/customer_telegram.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

void main() {
  testWidgets(
    'owner enables automatic recharge receipts with language and timezone',
    (tester) async {
      await tester.binding.setSurfaceSize(const Size(900, 1400));
      addTearDown(() => tester.binding.setSurfaceSize(null));
      var enabled = false;
      final api = Api(
        client: MockClient((request) async {
          if (request.method == 'PUT') {
            final body = jsonDecode(request.body);
            expect(body, {
              'enabled': true,
              'language': 'ar',
              'timezone': 'Asia/Baghdad',
            });
            enabled = true;
          }
          return http.Response(
            jsonEncode({
              'enabled': enabled,
              'selected_owner': true,
              'language': 'ar',
              'timezone': 'Asia/Baghdad',
            }),
            200,
          );
        }),
      )..user = {'role': 'owner'};
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(body: RechargeTelegramSettings(api: api)),
        ),
      );
      await tester.pumpAndSettle();
      await tester.tap(find.text('Send after every successful recharge'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Save recharge notifications'));
      await tester.pumpAndSettle();
      expect(enabled, isTrue);
      expect(
        find.text(
          'Automatic recharge notifications enabled from your Telegram account.',
        ),
        findsOneWidget,
      );
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets(
    'customer shows automatic receipt delivery status independently of bot link',
    (tester) async {
      await tester.binding.setSurfaceSize(const Size(900, 1600));
      addTearDown(() => tester.binding.setSurfaceSize(null));
      final api = Api(
        client: MockClient(
          (request) async => http.Response(
            jsonEncode(
              request.url.path.endsWith('/customer-telegram')
                  ? {'configured': false, 'enabled': false, 'can_manage': false}
                  : {
                      'linked': false,
                      'language': 'ar',
                      'language_managed': true,
                      'phone_available': true,
                      'phone_recharges_enabled': true,
                      'account_recharges': [
                        {
                          'kind': 'card',
                          'status': 'sent',
                          'detail':
                              'Telegram accepted the recharge notification.',
                          'created_at': '2026-11-15',
                        },
                      ],
                    },
            ),
            200,
          ),
        ),
      )..user = {'role': 'manager'};
      await tester.pumpWidget(
        MaterialApp(home: CustomerTelegram(api: api, customerId: 7)),
      );
      await tester.pumpAndSettle();
      expect(find.text('card · sent'), findsOneWidget);
      expect(
        find.textContaining('Automatic recharge receipts are enabled'),
        findsOneWidget,
      );
      expect(find.text('Customer not linked'), findsOneWidget);
      expect(
        tester
            .widget<DropdownButtonFormField<String>>(
              find.byType(DropdownButtonFormField<String>),
            )
            .onChanged,
        isNull,
      );
      expect(
        find.text(
          'Set for all ISP card customers in My account → Telegram account lookup.',
        ),
        findsOneWidget,
      );
      expect(tester.takeException(), isNull);
    },
  );
  testWidgets(
    'choosing a language immediately saves it without toggling delivery',
    (tester) async {
      await tester.binding.setSurfaceSize(const Size(900, 1400));
      addTearDown(() => tester.binding.setSurfaceSize(null));
      final writes = <Map<String, dynamic>>[];
      final api = Api(
        client: MockClient((request) async {
          if (request.method == 'PUT') {
            expect(
              request.url.path.endsWith('/recharge-telegram/language'),
              isTrue,
            );
            writes.add(jsonDecode(request.body));
          }
          return http.Response(
            jsonEncode({
              'enabled': false,
              'selected_owner': true,
              'language': writes.isEmpty ? 'en' : writes.last['language'],
              'timezone': 'Asia/Baghdad',
            }),
            200,
          );
        }),
      )..user = {'role': 'owner'};
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(body: RechargeTelegramSettings(api: api)),
        ),
      );
      await tester.pumpAndSettle();
      await tester.tap(find.text('Send after every successful recharge'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('English'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('العربية').last);
      await tester.pumpAndSettle();
      expect(writes, [
        {'language': 'ar'},
      ]);
      expect(
        find.text('Language saved for all ISP card customers.'),
        findsOneWidget,
      );
      expect(
        tester
            .widget<SwitchListTile>(
              find.widgetWithText(
                SwitchListTile,
                'Send after every successful recharge',
              ),
            )
            .value,
        isTrue,
      );
      expect(tester.takeException(), isNull);
    },
  );
}
