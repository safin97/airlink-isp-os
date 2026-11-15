import 'dart:convert';
import 'package:airlink_isp_os/api.dart';
import 'package:airlink_isp_os/notification_message_editor.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

void main() {
  testWidgets('edit, preview, save and reset a notification without sending', (
    tester,
  ) async {
    await tester.binding.setSurfaceSize(const Size(1000, 1800));
    addTearDown(() => tester.binding.setSurfaceSize(null));
    var saved = 'Hello {username}';
    final writes = <String>[];
    final api = Api(
      client: MockClient((request) async {
        expect(request.url.path.contains('/templates/ku/'), isTrue);
        expect(request.url.path.endsWith('/test'), isFalse);
        if (request.method == 'POST') {
          expect(request.url.path.endsWith('/preview'), isTrue);
          writes.add('preview');
          return http.Response('{"preview":"Custom sample-customer"}', 200);
        }
        if (request.method == 'PUT') {
          saved = jsonDecode(request.body)['text'];
          writes.add('save');
        }
        if (request.method == 'DELETE') {
          saved = 'Default {username}';
          writes.add('reset');
        }
        return http.Response(
          jsonEncode({
            'text': saved,
            'preview': 'Sample customer',
            'placeholders': ['username', 'details'],
          }),
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
    await tester.enterText(
      find.widgetWithText(TextField, 'Notification text'),
      'Custom {username}',
    );
    await tester.tap(find.text('Preview message'));
    await tester.pumpAndSettle();
    expect(saved, 'Hello {username}');
    expect(find.text('Custom sample-customer'), findsOneWidget);
    await tester.tap(find.text('Save message'));
    await tester.pumpAndSettle();
    expect(saved, 'Custom {username}');
    expect(find.text('Notification message saved.'), findsOneWidget);
    await tester.tap(find.text('Restore default'));
    await tester.pumpAndSettle();
    expect(saved, 'Default {username}');
    expect(writes, ['preview', 'save', 'reset']);
    expect(tester.takeException(), isNull);
  });
}
