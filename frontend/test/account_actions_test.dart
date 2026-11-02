import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:airlink_isp_os/api.dart';
import 'package:airlink_isp_os/main.dart';

void main() {
  testWidgets(
    'owner can edit and delete technician, viewer and manager accounts',
    (tester) async {
      tester.view.physicalSize = const Size(1440, 1000);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      final accounts = [
        {'id': 'owner', 'username': 'owner', 'role': 'owner', 'active': true},
        {
          'id': 'tech',
          'username': 'team',
          'role': 'technician',
          'active': false,
        },
        {
          'id': 'viewer',
          'username': 'viewer',
          'role': 'viewer',
          'active': true,
        },
        {
          'id': 'manager',
          'username': 'manager',
          'role': 'manager',
          'active': true,
        },
      ];
      final writes = <http.Request>[];
      final api = Api(
        client: MockClient((request) async {
          if (request.method != 'GET') {
            writes.add(request);
            return http.Response(
              request.method == 'DELETE' ? '' : '{}',
              request.method == 'DELETE' ? 204 : 200,
            );
          }
          return http.Response(
            jsonEncode(
              request.url.path == '/api/users'
                  ? accounts
                  : request.url.path == '/api/dashboard'
                  ? {}
                  : [],
            ),
            200,
          );
        }),
      )..user = {'id': 'owner', 'username': 'owner', 'role': 'owner'};
      await tester.pumpWidget(
        MaterialApp(
          home: Operations(api: api, logout: () async {}),
        ),
      );
      await tester.pumpAndSettle();
      await tester.tap(find.widgetWithText(ListTile, 'Managers'));
      await tester.pumpAndSettle();
      expect(
        find.byTooltip('Edit username, password or role'),
        findsNWidgets(3),
      );
      expect(find.byTooltip('Delete account'), findsNWidgets(3));
      await tester.tap(find.byTooltip('Edit username, password or role').first);
      await tester.pumpAndSettle();
      await tester.enterText(find.byType(TextFormField).first, 'updated-team');
      await tester.tap(find.byType(DropdownButtonFormField<String>));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Manager').last);
      await tester.pumpAndSettle();
      await tester.tap(find.text('Save'));
      await tester.pumpAndSettle();
      expect(writes.single.method, 'PUT');
      expect(writes.single.url.path, '/api/users/tech');
      expect(jsonDecode(writes.single.body), {
        'username': 'updated-team',
        'password': null,
        'role': 'manager',
      });
      await tester.tap(find.byTooltip('Delete account').first);
      await tester.pumpAndSettle();
      expect(find.text('Delete account team?'), findsOneWidget);
      await tester.tap(find.widgetWithText(FilledButton, 'Delete account'));
      await tester.pumpAndSettle();
      expect(writes.last.method, 'DELETE');
      expect(writes.last.url.path, '/api/users/tech');
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox());
    },
  );
}
