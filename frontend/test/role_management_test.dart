import 'dart:convert';
import 'account_type_fixtures.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:airlink_isp_os/api.dart';
import 'package:airlink_isp_os/main.dart';
import 'package:airlink_isp_os/role_management.dart';
import 'package:airlink_isp_os/section_access.dart';

void main() {
  testWidgets('access group saves independent read edit and delete grants', (
    tester,
  ) async {
    tester.view.physicalSize = const Size(1440, 1200);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);
    Map<String, dynamic>? saved;
    final api = Api(
      client: MockClient((r) async {
        expect(r.url.path, '/api/access-roles');
        expect(r.method, 'POST');
        saved = jsonDecode(r.body);
        return http.Response('{}', 201);
      }),
    );
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: RoleEditor(api: api, accessGroup: true, groups: const []),
        ),
      ),
    );
    await tester.enterText(find.byType(TextFormField), 'Cleanup team');
    final delete = find.byKey(const ValueKey('delete-towers'));
    expect(tester.widget<Checkbox>(delete).onChanged, isNull);
    await tester.tap(find.byKey(const ValueKey('read-towers')));
    await tester.pump();
    await tester.tap(delete);
    await tester.pump();
    expect(
      tester.widget<Checkbox>(find.byKey(const ValueKey('edit-towers'))).value,
      isFalse,
    );
    await tester.tap(find.text('Save'));
    await tester.pumpAndSettle();
    expect(saved, {
      'name': 'Cleanup team',
      'sections': ['towers'],
      'editable_sections': [],
      'deletable_sections': ['towers'],
    });
    expect(tester.takeException(), isNull);
  });

  testWidgets(
    'owner pages and manager account role selector are wired to API',
    (tester) async {
      tester.view.physicalSize = const Size(1440, 1200);
      tester.view.devicePixelRatio = 1;
      addTearDown(tester.view.resetPhysicalSize);
      addTearDown(tester.view.resetDevicePixelRatio);
      Map<String, dynamic>? saved;
      final api = Api(
        client: MockClient((r) async {
          if (r.method == 'PUT') {
            expect(r.url.path, '/api/users/m');
            saved = jsonDecode(r.body);
            return http.Response('{}', 200);
          }
          final Object data = switch (r.url.path) {
            '/api/users' => [
              {
                'id': 'm',
                'username': 'manager',
                'role': 'manager',
                'active': true,
              },
            ],
            '/api/access-roles' => [
              ...builtInAccountTypes,
              {'id': 'r', 'name': 'Support', 'access_role_name': 'Readers'},
            ],
            '/api/dashboard' => <String, dynamic>{},
            _ => [],
          };
          return http.Response(jsonEncode(data), 200);
        }),
      )..user = {'role': 'owner', 'username': 'owner'};
      await tester.pumpWidget(
        MaterialApp(
          home: Operations(api: api, logout: () async {}),
        ),
      );
      await tester.pumpAndSettle();
      expect(find.widgetWithText(ListTile, 'Roles'), findsNothing);
      expect(find.widgetWithText(ListTile, 'Access Roles'), findsOneWidget);
      await tester.tap(find.widgetWithText(ListTile, 'Managers'));
      await tester.pumpAndSettle();
      await tester.tap(find.byTooltip('Edit username, password or role'));
      await tester.pumpAndSettle();
      final field = find.byType(DropdownButtonFormField<String>).first;
      await tester.ensureVisible(field);
      await tester.tap(field);
      await tester.pumpAndSettle();
      await tester.tap(find.text('Support').last);
      await tester.pumpAndSettle();
      await tester.tap(find.text('Save'));
      await tester.pumpAndSettle();
      expect(saved!['access_role_id'], 'r');
      expect(saved!['role'], 'manager');
      expect(saved!.containsKey('place_ids'), isFalse);
      expect(tester.takeException(), isNull);
      await tester.pumpWidget(const SizedBox());
    },
  );

  test('delete and role administration stay independently gated', () {
    final user = <String, dynamic>{
      'role': 'manager',
      'sections': ['towers'],
      'editable_sections': [],
      'deletable_sections': ['towers'],
    };
    expect(canDeleteSection(user, 'towers'), isTrue);
    expect(canEditSection(user, 'towers'), isFalse);
    expect(hasSection(user, 'roles'), isFalse);
    expect(hasSection({'role': 'viewer'}, 'access_roles'), isFalse);
    user['sections'] = [];
    expect(canDeleteSection(user, 'towers'), isFalse);
  });
}
