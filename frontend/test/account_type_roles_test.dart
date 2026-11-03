import 'dart:convert';
import 'account_type_fixtures.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:airlink_isp_os/api.dart';
import 'package:airlink_isp_os/main.dart';

void main() {
  for (final editing in [false, true]) {
    testWidgets(
      '${editing ? 'edit' : 'add'} account chooses custom roles in Account type',
      (tester) async {
        tester.view.physicalSize = const Size(1440, 1200);
        tester.view.devicePixelRatio = 1;
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);
        Map<String, dynamic>? saved;
        var roleReads = 0;
        final api = Api(
          client: MockClient((r) async {
            if (r.method != 'GET') {
              expect(r.url.path, editing ? '/api/users/m' : '/api/users');
              saved = jsonDecode(r.body);
              return http.Response('{}', editing ? 200 : 201);
            }
            final Object data = switch (r.url.path) {
              '/api/dashboard' => <String, dynamic>{},
              '/api/access-roles' =>
                ++roleReads == 1 && !editing
                    ? builtInAccountTypes
                    : [
                        ...builtInAccountTypes,
                        {
                          'id': 'r',
                          'name': 'Support',
                          'access_role_name': 'Readers',
                        },
                      ],
              '/api/places' => [
                {'id': 'p', 'name': 'Zakho', 'tower_count': 0},
              ],
              '/api/users' => [
                if (editing)
                  {
                    'id': 'm',
                    'username': 'staff',
                    'role': 'manager',
                    'access_role_id': 'r',
                    'access_role_name': 'Support',
                    'place_ids': ['p'],
                    'parent_id': 'parent',
                    'active': true,
                  },
                {
                  'id': 'parent',
                  'username': 'regional.manager',
                  'role': 'manager',
                  'active': true,
                },
              ],
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
        await tester.tap(find.widgetWithText(ListTile, 'Managers'));
        await tester.pumpAndSettle();
        if (editing) {
          await tester.tap(
            find.byTooltip('Edit username, password or role').first,
          );
        } else {
          await tester.tap(find.text('Add account'));
        }
        await tester.pumpAndSettle();
        expect(roleReads, greaterThanOrEqualTo(2));
        expect(find.byType(DropdownButtonFormField<String>), findsNWidgets(2));
        expect(find.text('Account type'), findsOneWidget);
        if (editing) {
          expect(
            find.descendant(
              of: find.byType(DropdownButtonFormField<String>),
              matching: find.text('Support'),
            ),
            findsOneWidget,
          );
          // An unchanged custom type must preserve the role and place assignment.
          await tester.tap(find.text('Save'));
          await tester.pumpAndSettle();
          expect(saved!['role'], 'manager');
          expect(saved!['access_role_id'], 'r');
          expect(saved!.containsKey('place_ids'), isFalse);
          expect(saved!.containsKey('parent_id'), isFalse);
          await tester.tap(
            find.byTooltip('Edit username, password or role').first,
          );
          await tester.pumpAndSettle();
        } else {
          await tester.enterText(find.byType(TextFormField).first, 'new.staff');
          await tester.enterText(
            find.byType(TextFormField).last,
            'Example-Test-Password-534!',
          );
        }
        await tester.ensureVisible(
          find.widgetWithText(SwitchListTile, 'Show SNMP profiles'),
        );
        await tester.tap(
          find.widgetWithText(SwitchListTile, 'Show SNMP profiles'),
        );
        await tester.ensureVisible(
          find.byType(DropdownButtonFormField<String>).first,
        );
        await tester.tap(find.byType(DropdownButtonFormField<String>).first);
        await tester.pumpAndSettle();
        await tester.tap(find.text(editing ? 'Manager' : 'Support').last);
        await tester.pumpAndSettle();
        expect(find.text('Assigned places'), findsOneWidget);
        if (!editing) {
          await tester.tap(find.widgetWithText(CheckboxListTile, 'Zakho'));
        }
        await tester.tap(find.byType(DropdownButtonFormField<String>).last);
        await tester.pumpAndSettle();
        await tester.tap(find.text(editing ? 'None' : 'regional.manager').last);
        await tester.pumpAndSettle();
        await tester.tap(find.text('Save'));
        await tester.pumpAndSettle();
        expect(saved!['show_snmp_profiles'], true);
        expect(saved!['role'], 'manager');
        expect(saved!['parent_id'], editing ? isNull : 'parent');
        expect(saved!.containsKey('parent_id'), isTrue);
        expect(saved!['access_role_id'], editing ? isNull : 'r');
        if (!editing) expect(saved!['place_ids'], ['p']);
        expect(tester.takeException(), isNull);
        await tester.pumpWidget(const SizedBox());
      },
    );
  }
}
