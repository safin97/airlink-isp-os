import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:airlink_isp_os/api.dart';
import 'package:airlink_isp_os/telegram_settings.dart';

Map<String, dynamic> messageDefaults() => {
  'language': 'en',
  'down_message': 'Device: {device_name}\nTower: {tower_name}',
  'recovery_message': 'Custom recovery {device_name}',
  'default_message': 'Device: {device_name}\nTower: {tower_name}',
  'placeholders': ['status', 'device_name', 'tower_name', 'ip_address', 'time'],
  'languages': {
    'en': {
      'label': 'English',
      'rtl': false,
      'default_message': 'Device: {device_name}\nTower: {tower_name}',
      'down_status': 'DOWN',
      'recovery_status': 'RECOVERED',
    },
    'ar': {
      'label': 'العربية',
      'rtl': true,
      'default_message': 'الجهاز: {device_name}\nالبرج: {tower_name}',
      'down_status': 'غير متصل',
      'recovery_status': 'تمت استعادة الاتصال',
    },
  },
};

void main() {
  testWidgets('saves account notification language before sending test', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(1400, 1800);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    final requests = <http.Request>[];
    final api = Api(
      client: MockClient((request) async {
        requests.add(request);
        return http.Response(
          jsonEncode(
            request.url.path.endsWith('/messages')
                ? messageDefaults()
                : {'enabled': true, 'chat_id': '-123', 'has_token': true},
          ),
          200,
          headers: {'content-type': 'application/json; charset=utf-8'},
        );
      }),
    );
    api.user ??= {'role': 'owner'};
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: SingleChildScrollView(
            child: TelegramSettings(
              api: api,
              basePath: '/integrations/telegram/accounts/manager-1',
            ),
          ),
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.text('-123'), findsOneWidget);
    expect(
      find.text('Token saved securely. Leave blank to keep it.'),
      findsOneWidget,
    );
    expect(find.text('Notification language'), findsOneWidget);
    await tester.tap(find.byType(DropdownButtonFormField<String>));
    await tester.pumpAndSettle();
    await tester.tap(find.text('العربية').last);
    await tester.pumpAndSettle();
    await tester.tap(find.text('Save and send test'));
    await tester.pumpAndSettle();
    expect(requests.map((r) => r.method), ['GET', 'GET', 'PUT', 'PUT', 'POST']);
    expect(jsonDecode(requests[2].body).containsKey('bot_token'), false);
    expect(
      requests[3].url.path,
      '/api/integrations/telegram/accounts/manager-1/messages',
    );
    expect(jsonDecode(requests[3].body), {
      'language': 'ar',
      'down_message': 'الجهاز: {device_name}\nالبرج: {tower_name}',
      'recovery_message': 'Custom recovery {device_name}',
    });
    expect(
      requests.last.url.path,
      '/api/integrations/telegram/accounts/manager-1/test',
    );
    expect(find.text('Test notification sent.'), findsOneWidget);
  });
}
