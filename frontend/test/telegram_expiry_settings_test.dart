import 'dart:convert';
import 'package:airlink_isp_os/api.dart';
import 'package:airlink_isp_os/telegram_expiry_settings.dart';
import 'package:airlink_isp_os/notification_message_editor.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

void main() {
  testWidgets('expiry alerts start off and enable only on explicit toggle', (
    tester,
  ) async {
    var enabled = false;
    var writes = 0;
    final api = Api(
      client: MockClient((request) async {
        if (request.method == 'PUT') {
          writes++;
          enabled = jsonDecode(request.body)['enabled'];
        }
        return http.Response(jsonEncode({'enabled': enabled}), 200);
      }),
    )..user = {'role': 'owner'};
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(body: TelegramExpirySettings(api: api)),
      ),
    );
    await tester.pumpAndSettle();
    expect(writes, 0);
    expect(
      tester.widget<SwitchListTile>(find.byType(SwitchListTile)).value,
      isFalse,
    );
    await tester.tap(find.text('Automatic expiry alerts'));
    await tester.pumpAndSettle();
    expect(writes, 1);
    expect(enabled, isTrue);
  });

  testWidgets('editor offers both expiry message types without sending', (
    tester,
  ) async {
    await tester.binding.setSurfaceSize(const Size(1000, 1800));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    final paths = <String>[];
    final api = Api(
      client: MockClient((request) async {
        expect(request.method, 'GET');
        paths.add(request.url.path);
        return http.Response(
          '{"text":"Expiry {expiration}","preview":"Sample","placeholders":["expiration"]}',
          200,
        );
      }),
    )..user = {'role': 'owner'};
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: SingleChildScrollView(
            child: NotificationMessageEditor(api: api, language: 'ku'),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.text('Edit notification message'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Card PIN recharge').first);
    await tester.pumpAndSettle();
    await tester.tap(find.text('Expires in 3 days').last);
    await tester.pumpAndSettle();
    expect(paths.last.endsWith('/ku/expiry_3days'), isTrue);
    await tester.tap(find.text('Expires in 3 days').first);
    await tester.pumpAndSettle();
    await tester.tap(find.text('Service expired').last);
    await tester.pumpAndSettle();
    expect(paths.last.endsWith('/ku/expired'), isTrue);
    expect(tester.takeException(), isNull);
  });
}
