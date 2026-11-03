import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:airlink_isp_os/api.dart';
import 'package:airlink_isp_os/device_api_access_panel.dart';

void main() {
  testWidgets(
    'assign tower and SAS4 manager device logins without saving passwords in fields',
    (tester) async {
      tester.view.physicalSize = const Size(1400, 1800);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final writes = <dynamic>[];
      final api = Api(
        client: MockClient((request) async {
          if (request.url.path.endsWith('/managers')) {
            return http.Response('[{"id":4,"username":"North manager"}]', 200);
          }
          if (request.method == 'GET') {
            return http.Response(
              '{"towers":[{"id":"north","name":"North tower","username":"","has_password":false}],"isp_managers":[]}',
              200,
            );
          }
          final body = jsonDecode(request.body);
          writes.add(body);
          return http.Response(
            jsonEncode({
              'username': body['username'],
              'has_password': true,
              'enabled': true,
              'protocol': body['protocol'],
              'port': null,
              'verify_tls': true,
            }),
            200,
          );
        }),
      );
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: SingleChildScrollView(child: DeviceApiAccessPanel(api: api)),
          ),
        ),
      );
      await tester.pumpAndSettle();
      await tester.tap(find.text('Device API logins'));
      await tester.pumpAndSettle();
      await tester.tap(
        find.byKey(const ValueKey('device-api-target-tower-null')),
      );
      await tester.pumpAndSettle();
      await tester.tap(find.text('North tower').last);
      await tester.pumpAndSettle();
      await tester.enterText(
        find.byKey(const ValueKey('device-api-username')),
        'tower-admin',
      );
      await tester.enterText(
        find.byKey(const ValueKey('device-api-password')),
        'private-tower-login',
      );
      final connection = find.byWidgetPredicate(
        (w) =>
            w is DropdownButtonFormField<String> &&
            w.decoration.labelText == 'Connection',
      );
      await tester.tap(connection);
      await tester.pumpAndSettle();
      await tester.tap(find.text('HTTPS + HTTP (auto)').last);
      await tester.pumpAndSettle();
      expect(writes, isEmpty);
      await tester.tap(find.text('Save device login'));
      await tester.pumpAndSettle();
      expect(writes.single['scope'], 'tower');
      expect(writes.single['protocol'], 'both');
      expect(writes.single['target_id'], 'north');
      expect(
        tester
            .widget<TextField>(
              find.byKey(const ValueKey('device-api-password')),
            )
            .controller!
            .text,
        '',
      );
      final scope = find.byWidgetPredicate(
        (w) =>
            w is DropdownButtonFormField<String> &&
            w.decoration.labelText == 'Assign to',
      );
      await tester.tap(scope);
      await tester.pumpAndSettle();
      await tester.tap(find.text('ISP Card manager').last);
      await tester.pumpAndSettle();
      expect(
        tester
            .widget<TextField>(
              find.byKey(const ValueKey('device-api-username')),
            )
            .controller!
            .text,
        '',
      );
      await tester.tap(
        find.byKey(const ValueKey('device-api-target-isp_manager-null')),
      );
      await tester.pumpAndSettle();
      await tester.tap(find.text('North manager').last);
      await tester.pumpAndSettle();
      await tester.enterText(
        find.byKey(const ValueKey('device-api-username')),
        'manager-device-admin',
      );
      await tester.enterText(
        find.byKey(const ValueKey('device-api-password')),
        'private-manager-login',
      );
      await tester.tap(find.text('Save device login'));
      await tester.pumpAndSettle();
      expect(writes.last['scope'], 'isp_manager');
      expect(writes.last['target_id'], '4');
      expect(writes.last['password'], 'private-manager-login');
      expect(
        tester
            .widget<TextField>(
              find.byKey(const ValueKey('device-api-password')),
            )
            .controller!
            .text,
        '',
      );
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox());
    },
  );
}
