import 'dart:convert';
import 'package:airlink_isp_os/api.dart';
import 'package:airlink_isp_os/whatsapp.dart';
import 'package:airlink_isp_os/account_panel.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

void main() {
  final defaults = <String, dynamic>{
    'phone_number_id': '123456789',
    'business_account_id': '987654321',
    'api_version': 'v27.0',
    'language': 'en_US',
    'timezone': 'Asia/Baghdad',
    'recharge_template': 'airlink_recharge',
    'expiry_3days_template': 'airlink_expiry_3days',
    'expired_template': 'airlink_expired',
    'recharge': false,
    'expiry_3days': false,
    'expired': false,
    'token_saved': true,
    'selected_owner': true,
    'account_ready': true,
    'events': [],
  };
  Future<void> mount(WidgetTester tester, Widget child) async {
    await tester.binding.setSurfaceSize(const Size(1000, 2200));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(body: SingleChildScrollView(child: child)),
      ),
    );
    await tester.pumpAndSettle();
  }

  test('WhatsApp account settings appear only for owners', () {
    expect(
      accountPagesFor({'role': 'owner'}),
      contains('WhatsApp notifications'),
    );
    for (final role in ['manager', 'technician', 'viewer']) {
      expect(
        accountPagesFor({'role': role}),
        isNot(contains('WhatsApp notifications')),
      );
    }
  });

  testWidgets(
    'all three triggers save explicitly and saved token is preserved',
    (tester) async {
      var data = Map<String, dynamic>.from(defaults);
      final writes = <Map>[];
      final api = Api(
        client: MockClient((request) async {
          if (request.method == 'PUT') {
            final body = jsonDecode(request.body) as Map;
            writes.add(body);
            data.addAll(Map<String, dynamic>.from(body));
          }
          return http.Response(jsonEncode(data), 200);
        }),
      )..user = {'role': 'owner'};
      await mount(tester, WhatsAppSettings(api: api));
      expect(writes, isEmpty);
      expect(find.text('System user access token'), findsOneWidget);
      expect(
        tester.widget<TextField>(find.byType(TextField).at(2)).obscureText,
        isTrue,
      );
      for (final title in whatsappKinds.values) {
        final toggle = find.widgetWithText(SwitchListTile, title);
        await tester.ensureVisible(toggle);
        await tester.tap(toggle);
        await tester.pumpAndSettle();
      }
      expect(writes, isEmpty);
      await tester.ensureVisible(find.text('Save WhatsApp settings'));
      await tester.tap(find.text('Save WhatsApp settings'));
      await tester.pumpAndSettle();
      expect(writes, hasLength(1));
      expect(writes.single['access_token'], '');
      for (final kind in whatsappKinds.keys) {
        expect(writes.single[kind], isTrue);
      }
      expect(tester.takeException(), isNull);
    },
  );

  testWidgets(
    'connection check is explicit and disabled for unsaved settings',
    (tester) async {
      var checks = 0;
      final api = Api(
        client: MockClient((request) async {
          if (request.method == 'POST') {
            expect(request.url.path.endsWith('/check'), isTrue);
            checks++;
          }
          return http.Response(
            jsonEncode({
              ...defaults,
              'verified_at': checks > 0 ? '2026-11-17T12:00:00Z' : null,
            }),
            200,
          );
        }),
      );
      await mount(tester, WhatsAppSettings(api: api));
      expect(checks, 0);
      final button = find.widgetWithText(
        OutlinedButton,
        'Check connection and templates',
      );
      await tester.ensureVisible(button);
      await tester.tap(button);
      await tester.pumpAndSettle();
      expect(checks, 1);
      expect(
        find.text(
          'Connection and all three templates verified. No message was sent.',
        ),
        findsOneWidget,
      );
      final phone = find.widgetWithText(TextField, 'WhatsApp phone number ID');
      await tester.ensureVisible(phone);
      await tester.enterText(phone, '222222222');
      await tester.pumpAndSettle();
      expect(tester.widget<OutlinedButton>(button).onPressed, isNull);
      expect(checks, 1);
    },
  );

  testWidgets('customer opt-in and opt-out are explicit; no messages on open', (
    tester,
  ) async {
    var enabled = false;
    final writes = <bool>[];
    final api = Api(
      client: MockClient((request) async {
        expect(request.url.path.endsWith('/users/7'), isTrue);
        if (request.method == 'PUT') {
          enabled = jsonDecode(request.body)['enabled'];
          writes.add(enabled);
        }
        return http.Response(
          jsonEncode({
            'configured': true,
            'enabled': enabled,
            'phone': '9647501234567',
            'events': [],
          }),
          200,
        );
      }),
    );
    await tester.pumpWidget(
      MaterialApp(home: CustomerWhatsApp(api: api, customerId: 7)),
    );
    await tester.pumpAndSettle();
    expect(writes, isEmpty);
    await tester.tap(find.byType(SwitchListTile));
    await tester.pumpAndSettle();
    expect(writes, [true]);
    await tester.tap(find.byType(SwitchListTile));
    await tester.pumpAndSettle();
    expect(writes, [true, false]);
    expect(tester.takeException(), isNull);
  });

  testWidgets('failed customer save preserves state and surfaces error', (
    tester,
  ) async {
    final api = Api(
      client: MockClient((request) async {
        if (request.method == 'PUT') {
          return http.Response('{"detail":"Customer access changed."}', 409);
        }
        return http.Response(
          '{"configured":true,"enabled":false,"phone":"9647501234567","events":[]}',
          200,
        );
      }),
    );
    await tester.pumpWidget(
      MaterialApp(home: CustomerWhatsApp(api: api, customerId: 7)),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.byType(SwitchListTile));
    await tester.pumpAndSettle();
    expect(
      tester.widget<SwitchListTile>(find.byType(SwitchListTile)).value,
      isFalse,
    );
    expect(find.textContaining('Customer access changed.'), findsOneWidget);
  });
}
