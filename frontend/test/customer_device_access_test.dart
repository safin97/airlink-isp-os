import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:airlink_isp_os/api.dart';
import 'package:airlink_isp_os/customer_device_access.dart';

void main() {
  testWidgets('automatic readings save API and SNMP secrets write-only', (
    tester,
  ) async {
    Map<String, dynamic>? saved;
    final api = Api(
      client: MockClient((request) async {
        if (request.method == 'PUT') saved = jsonDecode(request.body);
        return http.Response(
          jsonEncode({
            'enabled': true,
            'api_username': 'monitor',
            'verify_tls': true,
            'allow_http': false,
            'has_community': true,
            'has_api_password': true,
            'saved_snmp_profiles': 2,
          }),
          200,
        );
      }),
    );
    api.user = {'role': 'owner'};
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: SingleChildScrollView(child: CustomerDeviceAccess(api: api)),
        ),
      ),
    );
    await tester.pumpAndSettle();
    await tester.tap(find.text('Default device login'));
    await tester.pumpAndSettle();
    expect(find.text('monitor'), findsOneWidget);
    expect(find.textContaining('SNMP v2c and v1'), findsWidgets);
    final fields = tester
        .widgetList<TextField>(find.byType(TextField))
        .toList();
    expect(fields[0].controller!.text, 'monitor');
    expect(fields[1].controller!.text, isEmpty);
    expect(fields[1].obscureText, isTrue);
    expect(fields[2].controller!.text, isEmpty);
    expect(fields[2].obscureText, isTrue);
    expect(fields.length, 3);
    await tester.ensureVisible(find.text('Save device login'));
    await tester.tap(find.text('Save device login'));
    await tester.pumpAndSettle();
    expect(saved!['community'], isNull);
    expect(saved!['api_username'], 'monitor');
    expect(saved!['api_password'], isNull);

    expect(saved!['verify_tls'], isTrue);
    expect(saved!['try_public_snmp'], isFalse);
    expect(saved!.containsKey('allow_http'), isTrue);
    expect(tester.takeException(), isNull);
  });
}
