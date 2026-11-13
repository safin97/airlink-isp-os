import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:airlink_isp_os/api.dart';
import 'package:airlink_isp_os/telegram_settings.dart';

void main() {
  testWidgets('loads masked connection and saves before sending test', (
    tester,
  ) async {
    final requests = <http.Request>[];
    final api = Api(
      client: MockClient((request) async {
        requests.add(request);
        return http.Response(
          jsonEncode({'enabled': true, 'chat_id': '-123', 'has_token': true}),
          200,
        );
      }),
    );
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: SingleChildScrollView(child: TelegramSettings(api: api)),
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.text('-123'), findsOneWidget);
    expect(
      find.text('Token saved securely. Leave blank to keep it.'),
      findsOneWidget,
    );
    await tester.tap(find.text('Save and send test'));
    await tester.pumpAndSettle();
    expect(requests.map((r) => r.method), ['GET', 'PUT', 'POST']);
    expect(jsonDecode(requests[1].body).containsKey('bot_token'), false);
    expect(requests.last.url.path, '/api/integrations/telegram/test');
    expect(find.text('Test notification sent.'), findsOneWidget);
  });
}
