import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:airlink_isp_os/api.dart';
import 'package:airlink_isp_os/customer_device_access.dart';

void main() {
  testWidgets(
    'customer access exposes only SNMP settings and keeps the community write-only',
    (tester) async {
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
      await tester.tap(find.text('Customer device access'));
      await tester.pumpAndSettle();
      expect(find.text('monitor'), findsNothing);
      expect(find.text('Device API username'), findsNothing);
      final fields = tester
          .widgetList<TextField>(find.byType(TextField))
          .toList();
      expect(fields[0].controller!.text, isEmpty);
      expect(fields.length, 1);
      await tester.ensureVisible(find.text('Save device access'));
      await tester.tap(find.text('Save device access'));
      await tester.pumpAndSettle();
      expect(saved!['community'], isNull);
      expect(saved!.containsKey('api_password'), isFalse);
      expect(saved!.containsKey('verify_tls'), isFalse);
      expect(saved!['try_public_snmp'], isTrue);
      expect(saved!.containsKey('allow_http'), isFalse);
      expect(tester.takeException(), isNull);
    },
  );
}
