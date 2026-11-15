import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:airlink_isp_os/api.dart';
import 'package:airlink_isp_os/telegram_messages.dart';

void main() {
  testWidgets('edits previews and saves personal message templates', (
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
          jsonEncode({
            'down_message': 'Down: {device_name}',
            'recovery_message': '{status}: {device_name}',
            'default_message': '{status}: {device_name}',
            'language': 'en',
            'languages': {
              'en': {
                'label': 'English',
                'rtl': false,
                'default_message': '{status}: {device_name}',
                'down_status': 'DOWN / TIMEOUT',
                'recovery_status': 'RECOVERED',
              },
              'ar': {
                'label': 'العربية',
                'rtl': true,
                'default_message':
                    '{status}: {device_name}\nالبرج: {tower_name}',
                'down_status': 'غير متصل',
                'recovery_status': 'تمت استعادة الاتصال',
              },
              'ku': {
                'label': 'کوردی (بادینی)',
                'rtl': true,
                'default_message':
                    '{status}: {device_name}\nتاوەر: {tower_name}',
                'down_status': 'دەرەڤەی هێڵێ',
                'recovery_status': 'دووبارە سەرهێڵ',
              },
            },
            'placeholders': [
              'status',
              'device_name',
              'ip_address',
              'tower_name',
              'time',
            ],
          }),
          200,
          headers: {'content-type': 'application/json; charset=utf-8'},
        );
      }),
    );
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: SingleChildScrollView(child: TelegramMessages(api: api)),
        ),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.text('Down: Example router'), findsOneWidget);
    await tester.enterText(
      find.byType(TextField).first,
      'Offline {device_name} at {tower_name}',
    );
    await tester.pump();
    expect(
      find.text('Offline Example router at Example tower'),
      findsOneWidget,
    );
    await tester.tap(find.byType(DropdownButtonFormField<String>));
    await tester.pumpAndSettle();
    expect(find.text('کوردی (بادینی)'), findsOneWidget);
    await tester.tap(find.text('العربية').last);
    await tester.pumpAndSettle();
    // Custom down wording survives; the untouched recovery default translates.
    expect(
      find.text('Offline Example router at Example tower'),
      findsOneWidget,
    );
    expect(
      find.text('تمت استعادة الاتصال: Example router\nالبرج: Example tower'),
      findsOneWidget,
    );
    expect(
      tester.widget<TextField>(find.byType(TextField).first).textDirection,
      TextDirection.rtl,
    );
    await tester.tap(find.text('Save messages'));
    await tester.pumpAndSettle();
    expect(requests.last.method, 'PUT');
    expect(jsonDecode(requests.last.body)['language'], 'ar');
    expect(
      jsonDecode(requests.last.body)['down_message'],
      'Offline {device_name} at {tower_name}',
    );
    await tester.tap(find.text('Restore defaults'));
    await tester.pump();
    expect(
      find.text('غير متصل: Example router\nالبرج: Example tower'),
      findsOneWidget,
    );
    expect(requests.length, 2);
  });
}
