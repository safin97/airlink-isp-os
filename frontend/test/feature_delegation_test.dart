import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:airlink_isp_os/api.dart';
import 'package:airlink_isp_os/account_panel.dart';
import 'package:airlink_isp_os/payment_settings.dart';
import 'package:airlink_isp_os/section_access.dart';

void main() {
  test('new administrative grants default off and actions are independent', () {
    expect(
      canFeatureRequest(
        {'role': 'owner', 'visible_sections': []},
        '/integrations/ttlock',
        'GET',
        null,
      ),
      true,
    );
    final user = <String, dynamic>{'role': 'manager'};
    for (final key in administrativeSections.keys) {
      expect(hasSection(user, key), false, reason: key);
      expect(canEditSection(user, key), false, reason: key);
      expect(canDeleteSection(user, key), false, reason: key);
    }
    user['sections'] = administrativeSections.keys.toList();
    for (final key in administrativeSections.keys) {
      expect(hasSection(user, key), true, reason: key);
      expect(canEditSection(user, key), false, reason: key);
      expect(canDeleteSection(user, key), false, reason: key);
    }
    user['editable_sections'] = ['ttlock'];
    user['deletable_sections'] = ['card_system'];
    expect(canEditSection(user, 'ttlock'), true);
    expect(canDeleteSection(user, 'ttlock'), false);
    expect(canEditSection(user, 'card_system'), false);
    expect(canDeleteSection(user, 'card_system'), true);
    expect(accountPagesFor(user).keys, contains('Payment setup'));
    user['sections'] = <String>[];
    expect(accountPagesFor(user).keys, isNot(contains('Payment setup')));
  });

  test(
    'API guard blocks mutations and POST deletion without sending requests',
    () async {
      var calls = 0;
      final api =
          Api(
              client: MockClient((request) async {
                calls++;
                return http.Response('{}', 200);
              }),
            )
            ..user = {
              'role': 'manager',
              'sections': ['ttlock', 'vpn'],
              'editable_sections': ['ttlock'],
              'deletable_sections': ['vpn'],
            };
      await expectLater(
        api.request(
          '/integrations/ttlock/mobile/prepare',
          method: 'POST',
          body: {'action': 'card_delete'},
        ),
        throwsA(isA<ApiException>()),
      );
      await expectLater(
        api.request('/vpn/connect', method: 'POST'),
        throwsA(isA<ApiException>()),
      );
      expect(calls, 0);
      await api.request('/vpn/delete', method: 'POST');
      expect(calls, 1);
      api.user!['deletable_sections'] = <String>[];
      await expectLater(
        api.request('/vpn/delete', method: 'POST'),
        throwsA(isA<ApiException>()),
      );
      expect(calls, 1);
    },
  );

  testWidgets('delegated payment settings View loads but cannot save', (
    tester,
  ) async {
    final requests = <http.Request>[];
    final api =
        Api(
            client: MockClient((request) async {
              requests.add(request);
              return http.Response(
                jsonEncode([
                  {
                    'provider': 'fib',
                    'configured': true,
                    'environment': 'sandbox',
                    'merchant_id': 'merchant',
                  },
                  {
                    'provider': 'fastpay',
                    'configured': false,
                    'environment': 'sandbox',
                    'merchant_id': '',
                  },
                ]),
                200,
              );
            }),
          )
          ..user = {
            'role': 'manager',
            'sections': ['payment_gateways'],
            'editable_sections': [],
            'deletable_sections': [],
          };
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
    expect(requests.map((r) => r.method), ['GET']);
    expect(find.text('FIB client ID'), findsOneWidget);
    for (final button in tester.widgetList<FilledButton>(
      find.byType(FilledButton),
    )) {
      expect(button.onPressed, isNull);
    }
    for (final field in tester.widgetList<TextField>(find.byType(TextField))) {
      expect(field.enabled, false);
    }
  });
}
