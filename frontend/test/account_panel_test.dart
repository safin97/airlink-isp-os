import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:airlink_isp_os/api.dart';
import 'package:airlink_isp_os/main.dart';

void main() {
  testWidgets(
    'top-right account opens profile, password change and SAS4 settings',
    (tester) async {
      tester.view.physicalSize = const Size(1440, 1400);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final writes = <http.Request>[];
      final api = Api(
        client: MockClient((request) async {
          if (request.method == 'PUT') {
            writes.add(request);
            return http.Response('{"ok":true}', 200);
          }
          return http.Response(
            jsonEncode(
              request.url.path == '/api/dashboard'
                  ? {}
                  : request.url.path == '/api/integrations/sas4'
                  ? {'username': '', 'configured': false}
                  : [],
            ),
            200,
          );
        }),
      )..user = {'username': 'my-manager', 'role': 'manager'};
      await tester.pumpWidget(
        MaterialApp(
          home: Operations(api: api, logout: () async {}),
        ),
      );
      await tester.pumpAndSettle();
      await tester.tap(find.widgetWithText(TextButton, 'my-manager'));
      await tester.pumpAndSettle();
      expect(find.text('My account'), findsOneWidget);
      expect(find.text('Role: manager'), findsOneWidget);
      expect(find.text('SAS4 connection'), findsOneWidget);
      await tester.enterText(
        find.byType(TextFormField).at(0),
        'Current-Password-573!',
      );
      await tester.enterText(
        find.byType(TextFormField).at(1),
        'New-Password-For-Account-492!',
      );
      await tester.enterText(
        find.byType(TextFormField).at(2),
        'New-Password-For-Account-492!',
      );
      await tester.ensureVisible(find.widgetWithText(FilledButton, 'Change password'));
    await tester.tap(find.widgetWithText(FilledButton, 'Change password'));
      await tester.pumpAndSettle();
      expect(writes.single.url.path, '/api/auth/password');
      expect(jsonDecode(writes.single.body), {
        'current_password': 'Current-Password-573!',
        'new_password': 'New-Password-For-Account-492!',
        'confirm_password': 'New-Password-For-Account-492!',
      });
      expect(
        find.text(
          'Password changed. Your other sessions have been signed out.',
        ),
        findsOneWidget,
      );
      expect(
        tester
            .widget<TextFormField>(find.byType(TextFormField).first)
            .controller!
            .text,
        isEmpty,
      );
      await tester.tap(find.text('Done'));
      await tester.pumpAndSettle();
      expect(find.text('My account'), findsNothing);
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox());
    },
  );
}
