import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:airlink_isp_os/api.dart';
import 'package:airlink_isp_os/main.dart';

void main() {
  testWidgets(
    'sidebar profile panel saves credentials and edits without password readback',
    (tester) async {
      tester.view.physicalSize = const Size(1600, 1400);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final profiles = <Map<String, dynamic>>[];
      final saved = <Map<String, dynamic>>[];
      final api = Api(
        client: MockClient((request) async {
          dynamic body = request.url.path.endsWith('/dashboard')
              ? <String, dynamic>{}
              : [];
          if (request.url.path.endsWith('/device-access')) {
            body = {
              'enabled': true,
              'api_username': 'reader',
              'has_api_password': true,
            };
          }
          if (request.url.path.endsWith('/device-login-profiles/managers')) {
            body = [
              {'id': 'manager-1', 'username': 'north-manager'},
            ];
          } else if (request.url.path.contains('/device-login-profiles')) {
            if (request.method == 'GET') {
              body = profiles;
            } else {
              final payload = Map<String, dynamic>.from(
                jsonDecode(request.body),
              );
              saved.add(payload);
              profiles.clear();
              profiles.add({
                'id': 'p',
                'name': payload['name'],
                'username': payload['username'],
                'protocol': payload['protocol'],
                'verify_tls': payload['verify_tls'],
                'enabled': true,
                'has_password': true,
              });
              body = profiles.single;
            }
          }
          return http.Response(
            jsonEncode(body),
            request.method == 'POST' ? 201 : 200,
          );
        }),
      )..user = {'role': 'owner', 'username': 'owner'};
      await tester.pumpWidget(
        MaterialApp(
          home: Operations(api: api, logout: () async {}),
        ),
      );
      await tester.pumpAndSettle();
      final nav = find.widgetWithText(ListTile, 'Device login');
      await tester.ensureVisible(nav);
      await tester.tap(nav);
      await tester.pumpAndSettle();
      expect(find.text('Default device login'), findsOneWidget);
      await tester.tap(find.text('Add profile'));
      await tester.pumpAndSettle();
      await tester.enterText(
        find.widgetWithText(TextFormField, 'Profile name'),
        'Roof devices',
      );
      await tester.enterText(
        find.widgetWithText(TextFormField, 'Device username'),
        'reader',
      );
      await tester.enterText(
        find.widgetWithText(TextFormField, 'Device password'),
        'device-test-password',
      );
      await tester.tap(find.widgetWithText(CheckboxListTile, 'north-manager'));
      await tester.tap(find.text('Save profile'));
      await tester.pumpAndSettle();
      expect(saved.single['password'], 'device-test-password');
      expect(saved.single['protocol'], 'both');
      expect(saved.single['manager_ids'], ['manager-1']);
      expect(find.text('Roof devices'), findsOneWidget);
      expect(find.text('device-test-password'), findsNothing);
      await tester.tap(find.byTooltip('Edit profile'));
      await tester.pumpAndSettle();
      final secret = tester.widget<TextFormField>(
        find.widgetWithText(TextFormField, 'Device password'),
      );
      expect(secret.controller!.text, isEmpty);
      await tester.enterText(
        find.widgetWithText(TextFormField, 'Profile name'),
        'Roof login',
      );
      await tester.tap(find.text('Save profile'));
      await tester.pumpAndSettle();
      expect(saved.last['password'], isNull);
      expect(saved.last['name'], 'Roof login');
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox());
    },
  );
}
